using System.Net;
using System.Net.Sockets;
using System.Text;
using TradingOs.Contracts;

namespace TradingOs.Gateway;

/// <summary>
/// TCP listener for the MT5 execution agent (EA-05, ADR 0010). Inverts the
/// topology of <see cref="Mt5ObserverClient"/>: there the Gateway dials OUT
/// to the Python observer, which is the WS server; here the Gateway IS the
/// server and the execution agent dials IN, per ADR 0010's own note that
/// this inversion was always the intended shape for the real agent.
///
/// Plain TCP, newline-delimited lean JSON — not WSS. The connection is
/// loopback-only by default, between two processes on the same personal
/// machine (ADR 0003: "usage strictement personnel") — <paramref name="bindAddress"/>
/// exists only so the Docker image can bind all interfaces internally
/// (a container's own loopback isn't reachable through its published
/// ports); docker-compose.yml still restricts the host-side publish to
/// 127.0.0.1, so the personal/single-machine posture is unchanged from
/// outside the container. Native runs never pass this, so they keep
/// binding loopback-only exactly as before. The existing Gateway&lt;-&gt;observer
/// link already runs unencrypted `ws://`, so WSS buys nothing real here,
/// and hand-rolling the HTTP-Upgrade handshake plus RFC 6455 frame masking
/// in pure MQL5 would be a needless source of bugs for that zero benefit
/// (decision recorded in context/product/tools/EA-05-agent-mql5.md). The
/// JSON message SHAPES are unchanged (lib/contracts/mt5-wire.ts / Mt5Wire.cs)
/// — only the framing differs from mt5_wire_protocol.md's original "WSS"
/// wording. Lines are written as UTF-8 WITHOUT a byte-order mark: a
/// `StreamWriter` over a non-seekable NetworkStream with `Encoding.UTF8`
/// writes EF BB BF before its first line, which would have prefixed the
/// first command ever sent to the agent.
///
/// Registry (2026-09-25): one registration per accountId, owned by the
/// connection whose agent.hello made it. A closing connection only ever
/// removes its OWN registration — the old code removed by key, so a second
/// instance or a quick reconnect left a live agent reported disconnected.
/// A second hello for an account whose agent is alive is refused and its
/// connection closed (ADR 0010: one agent per environment). A connection
/// silent for longer than <paramref name="staleAfter"/> is a dead agent
/// (terminal crash, half-open TCP): the watchdog closes it, and a new hello
/// for its account replaces it at once. The agent heartbeats every
/// InpHeartbeatSeconds (default 5), so the 30 s default is six missed beats.
///
/// Distinct and NEVER merged with Mt5ObserverClient (ADR 0010: "deux
/// processus, deux responsabilités, jamais fusionnés"). The Python observer
/// keeps streaming read-only market/account telemetry over its own
/// WebSocket; this class exists only for the execution agent's connection,
/// heartbeat, command delivery, and ack/report receipt.
///
/// Loopback socket tests cover the registry and the framing
/// (Mt5AgentServerTests); the behaviour against a real terminal is still
/// verified by hand (tools/mt5-execution-agent/README.md).
/// </summary>
public sealed class Mt5AgentServer(
    int port,
    IPAddress? bindAddress = null,
    TimeSpan? staleAfter = null,
    TimeSpan? watchdogPeriod = null)
{
    private static readonly Encoding Utf8NoBom = new UTF8Encoding(encoderShouldEmitUTF8Identifier: false);

    private readonly object _lock = new();
    private readonly Dictionary<string, AgentConnection> _byAccountId = new();
    private readonly HashSet<AgentConnection> _open = new();
    private readonly TimeSpan _staleAfter = staleAfter ?? TimeSpan.FromSeconds(30);
    private readonly TaskCompletionSource<int> _listening = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private TcpListener? _listener;

    /// <summary>Translated envelope ready to broadcast (type + camelCase payload object).</summary>
    public event Action<string, object>? EnvelopeReady;

    /// <summary>Raised after every registry change with whether at least one
    /// agent is still registered — true on each accepted hello, the aggregate
    /// when a registered connection goes away. Never raised for a connection
    /// that was never registered (a refused duplicate, a silent socket).</summary>
    public event Action<bool>? ConnectionChanged;

    /// <summary>A hello refused because another live connection already
    /// serves that account — carries the refused hello's agentId.</summary>
    public event Action<string>? DuplicateAgentRefused;

    /// <summary>Completes with the bound port once the listener has started.</summary>
    public Task<int> Listening => _listening.Task;

    /// <summary>True when at least one agent connection is currently registered.</summary>
    public bool IsConnected
    {
        get
        {
            lock (_lock)
            {
                return _byAccountId.Count > 0;
            }
        }
    }

    /// <summary>The hello of the agent currently registered for
    /// <paramref name="accountId"/> — per account, never "whichever agent
    /// said hello last".</summary>
    public Mt5HelloMessage? GetHello(string accountId)
    {
        lock (_lock)
        {
            return _byAccountId.TryGetValue(accountId, out var connection) ? connection.Hello : null;
        }
    }

    /// <summary>
    /// Sends one lean command line to the agent registered for
    /// <paramref name="accountId"/>. Returns false if no agent for that
    /// account is currently connected — the caller (CockpitHub) must treat
    /// that as AGENT_UNREACHABLE, never as a silent no-op.
    /// </summary>
    public async Task<bool> SendCommandAsync(string accountId, string json, CancellationToken ct)
    {
        AgentConnection? connection;
        lock (_lock)
        {
            _byAccountId.TryGetValue(accountId, out connection);
        }
        return connection is not null && await connection.TryWriteLineAsync(json, ct);
    }

    /// <summary>Wire report status → the event type lib/contracts/events.ts
    /// declares for it. Anything else (REJECTED — the agent sends an ack
    /// REJECTED just before it — or an unknown status) keeps travelling as
    /// execution.command.rejected, as it always has.</summary>
    public static string ReportEventType(string status) => status switch
    {
        "SIMULATED" => EventTypes.ExecutionOrderSimulated,
        "SUBMITTED" => EventTypes.ExecutionOrderSubmitted,
        "FILLED" => EventTypes.ExecutionOrderFilled,
        "PARTIALLY_FILLED" => EventTypes.ExecutionOrderPartiallyFilled,
        "FAILED" => EventTypes.ExecutionOrderFailed,
        _ => EventTypes.ExecutionCommandRejected,
    };

    public async Task RunAsync(CancellationToken ct)
    {
        _listener = new TcpListener(bindAddress ?? IPAddress.Loopback, port);
        _listener.Start();
        _listening.TrySetResult(((IPEndPoint)_listener.LocalEndpoint).Port);
        using var stop = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var watchdog = WatchdogAsync(stop.Token);
        try
        {
            while (!ct.IsCancellationRequested)
            {
                TcpClient client;
                try
                {
                    client = await _listener.AcceptTcpClientAsync(ct);
                }
                catch (OperationCanceledException)
                {
                    return;
                }
                _ = HandleClientAsync(client, ct);
            }
        }
        finally
        {
            stop.Cancel();
            _listener.Stop();
            await watchdog;
        }
    }

    /// <summary>Closes every connection silent for longer than staleAfter —
    /// registered or not — so a dead agent stops counting as connected and a
    /// half-open socket never holds an account.</summary>
    private async Task WatchdogAsync(CancellationToken ct)
    {
        var period = watchdogPeriod ?? _staleAfter / 2;
        if (watchdogPeriod is null && period > TimeSpan.FromSeconds(5))
        {
            period = TimeSpan.FromSeconds(5);
        }
        try
        {
            while (!ct.IsCancellationRequested)
            {
                await Task.Delay(period, ct);
                List<AgentConnection> silent;
                lock (_lock)
                {
                    silent = _open.Where(c => c.IsSilentFor(_staleAfter)).ToList();
                }
                foreach (var connection in silent)
                {
                    connection.Close(); // its read loop ends; HandleClientAsync unregisters it
                }
            }
        }
        catch (OperationCanceledException)
        {
            // shutting down
        }
    }

    private async Task HandleClientAsync(TcpClient client, CancellationToken ct)
    {
        using var _client = client;
        await using var stream = client.GetStream();
        var connection = new AgentConnection(client, new StreamWriter(stream, Utf8NoBom) { AutoFlush = true, NewLine = "\n" });
        using var reader = new StreamReader(stream, Encoding.UTF8);
        lock (_lock)
        {
            _open.Add(connection);
        }

        try
        {
            while (!ct.IsCancellationRequested && !connection.IsClosed)
            {
                var line = await reader.ReadLineAsync(ct);
                if (line is null)
                {
                    break; // agent closed the connection
                }
                connection.Touch();
                Handle(line, connection);
            }
        }
        catch (OperationCanceledException)
        {
            // shutting down
        }
        catch
        {
            // malformed frame, dropped connection, or closed by the watchdog /
            // a refused hello: close and let the agent reconnect — never crash
            // the gateway.
        }
        finally
        {
            bool removed;
            bool stillConnected;
            lock (_lock)
            {
                _open.Remove(connection);
                removed = connection.AccountId is { } accountId
                    && _byAccountId.TryGetValue(accountId, out var current)
                    && ReferenceEquals(current, connection)
                    && _byAccountId.Remove(accountId);
                stillConnected = _byAccountId.Count > 0;
            }
            connection.Close();
            if (removed)
            {
                ConnectionChanged?.Invoke(stillConnected);
            }
        }
    }

    /// <summary>Handles one incoming line.</summary>
    private void Handle(string json, AgentConnection connection)
    {
        Mt5Message? message;
        try
        {
            message = Mt5WireParser.Parse(json);
        }
        catch
        {
            return; // malformed frame: drop, never crash the gateway
        }

        var agentId = connection.Hello?.AgentId ?? "mt5-execution-agent";
        switch (message)
        {
            case Mt5HelloMessage hello:
                Register(hello, connection);
                return;
            case Mt5HeartbeatMessage heartbeat:
                EnvelopeReady?.Invoke(EventTypes.AgentHeartbeat, new AgentHeartbeatPayload(heartbeat.AgentId, heartbeat.LatencyMs));
                return;
            case Mt5AckMessage ack:
            {
                var mapped = Mt5WireTranslator.ToCommandAck(ack, agentId);
                var type = mapped.Status is "accepted" or "duplicate"
                    ? EventTypes.ExecutionCommandAcknowledged
                    : EventTypes.ExecutionCommandRejected;
                EnvelopeReady?.Invoke(type, new CommandAckPayload(mapped));
                return;
            }
            case Mt5ReportMessage report:
            {
                var mapped = Mt5WireTranslator.ToExecutionReport(report, agentId);
                EnvelopeReady?.Invoke(ReportEventType(report.Status), new ExecutionReportPayload(mapped));
                return;
            }
            case Mt5ReconciledMessage reconciled:
            {
                var mapped = Mt5WireTranslator.ToReconciled(reconciled, agentId);
                EnvelopeReady?.Invoke(EventTypes.ExecutionReconciled, new ReconciledPayload(mapped));
                return;
            }
            case Mt5PositionScannedMessage scanned:
            {
                var mapped = Mt5WireTranslator.ToPositionScanned(scanned, agentId);
                EnvelopeReady?.Invoke(EventTypes.ExecutionPositionScan, new PositionScannedPayload(mapped));
                return;
            }
            default:
                return; // unknown/unused types are ignored in this slice
        }
    }

    private void Register(Mt5HelloMessage hello, AgentConnection connection)
    {
        AgentConnection? replaced = null;
        bool accepted;
        bool gaveUpPrevious = false;
        bool stillConnected;
        lock (_lock)
        {
            // A connection re-announcing itself under another account (the
            // terminal switched accounts) gives up its previous registration.
            if (connection.AccountId is { } previous && previous != hello.AccountId
                && _byAccountId.TryGetValue(previous, out var own) && ReferenceEquals(own, connection))
            {
                _byAccountId.Remove(previous);
                gaveUpPrevious = true;
            }

            if (_byAccountId.TryGetValue(hello.AccountId, out var existing) && !ReferenceEquals(existing, connection))
            {
                accepted = existing.IsSilentFor(_staleAfter);
                if (accepted)
                {
                    replaced = existing;
                }
            }
            else
            {
                accepted = true;
            }

            if (accepted)
            {
                _byAccountId[hello.AccountId] = connection;
                connection.AccountId = hello.AccountId;
                connection.Hello = hello;
            }
            stillConnected = _byAccountId.Count > 0;
        }

        if (!accepted)
        {
            DuplicateAgentRefused?.Invoke(hello.AgentId);
            connection.Close();
            if (gaveUpPrevious)
            {
                ConnectionChanged?.Invoke(stillConnected);
            }
            return;
        }

        replaced?.Close(); // its own finally finds it no longer registered: no removal, no event
        ConnectionChanged?.Invoke(true);
        EnvelopeReady?.Invoke(EventTypes.AgentConnected, new { agentId = hello.AgentId });
    }

    /// <summary>One agent socket: its writer (serialized — concurrent hub
    /// invocations must not interleave lines), its registration, and when it
    /// last said anything. AccountId and Hello are guarded by the server's
    /// lock.</summary>
    private sealed class AgentConnection(TcpClient client, StreamWriter writer)
    {
        private readonly SemaphoreSlim _writeLock = new(1, 1);
        private long _lastSeen = Environment.TickCount64;
        private int _closed;

        public string? AccountId { get; set; }

        public Mt5HelloMessage? Hello { get; set; }

        public bool IsClosed => Volatile.Read(ref _closed) == 1;

        public void Touch() => Interlocked.Exchange(ref _lastSeen, Environment.TickCount64);

        public bool IsSilentFor(TimeSpan span) =>
            Environment.TickCount64 - Interlocked.Read(ref _lastSeen) > (long)span.TotalMilliseconds;

        public async Task<bool> TryWriteLineAsync(string line, CancellationToken ct)
        {
            if (IsClosed)
            {
                return false;
            }
            await _writeLock.WaitAsync(ct);
            try
            {
                await writer.WriteLineAsync(line.AsMemory(), ct);
                return true;
            }
            catch
            {
                return false;
            }
            finally
            {
                _writeLock.Release();
            }
        }

        public void Close()
        {
            if (Interlocked.Exchange(ref _closed, 1) == 0)
            {
                client.Close();
            }
        }
    }
}
