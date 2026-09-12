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
/// loopback-only, between two processes on the same personal machine
/// (ADR 0003: "usage strictement personnel"); the existing Gateway&lt;-&gt;observer
/// link already runs unencrypted `ws://`, so WSS buys nothing real here,
/// and hand-rolling the HTTP-Upgrade handshake plus RFC 6455 frame masking
/// in pure MQL5 would be a needless source of bugs for that zero benefit
/// (decision recorded in context/product/tools/EA-05-agent-mql5.md). The
/// JSON message SHAPES are unchanged (lib/contracts/mt5-wire.ts / Mt5Wire.cs)
/// — only the framing differs from mt5_wire_protocol.md's original "WSS"
/// wording.
///
/// Distinct and NEVER merged with Mt5ObserverClient (ADR 0010: "deux
/// processus, deux responsabilités, jamais fusionnés"). The Python observer
/// keeps streaming read-only market/account telemetry over its own
/// WebSocket; this class exists only for the execution agent's connection,
/// heartbeat, command delivery, and ack/report receipt.
///
/// Like Mt5ObserverClient, this class is integration-tested against a real
/// terminal, not unit-tested — the same precedent this codebase already
/// sets for socket-handling classes (Mt5WireTranslator carries the tested
/// pure logic both classes call into).
/// </summary>
public sealed class Mt5AgentServer(int port)
{
    private readonly object _lock = new();
    private readonly Dictionary<string, StreamWriter> _writersByAccountId = new();
    private TcpListener? _listener;

    /// <summary>Translated envelope ready to broadcast (type + camelCase payload object).</summary>
    public event Action<string, object>? EnvelopeReady;

    /// <summary>An agent connected (true) or its connection was lost (false).</summary>
    public event Action<bool>? ConnectionChanged;

    public Mt5HelloMessage? Hello { get; private set; }

    /// <summary>True when at least one agent connection is currently open.</summary>
    public bool IsConnected
    {
        get
        {
            lock (_lock)
            {
                return _writersByAccountId.Count > 0;
            }
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
        StreamWriter? writer;
        lock (_lock)
        {
            _writersByAccountId.TryGetValue(accountId, out writer);
        }
        if (writer is null)
        {
            return false;
        }
        try
        {
            await writer.WriteLineAsync(json.AsMemory(), ct);
            return true;
        }
        catch
        {
            return false;
        }
    }

    public async Task RunAsync(CancellationToken ct)
    {
        _listener = new TcpListener(IPAddress.Loopback, port);
        _listener.Start();
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
            _listener.Stop();
        }
    }

    private async Task HandleClientAsync(TcpClient client, CancellationToken ct)
    {
        using var _client = client;
        await using var stream = client.GetStream();
        var writer = new StreamWriter(stream, Encoding.UTF8) { AutoFlush = true, NewLine = "\n" };
        using var reader = new StreamReader(stream, Encoding.UTF8);
        string? accountId = null;

        try
        {
            while (!ct.IsCancellationRequested)
            {
                var line = await reader.ReadLineAsync(ct);
                if (line is null)
                {
                    break; // agent closed the connection
                }
                var seenAccountId = Handle(line, writer);
                if (seenAccountId is not null)
                {
                    accountId = seenAccountId;
                }
            }
        }
        catch (OperationCanceledException)
        {
            // shutting down
        }
        catch
        {
            // malformed frame or dropped connection: close and let the agent
            // reconnect — never crash the gateway.
        }
        finally
        {
            if (accountId is not null)
            {
                lock (_lock)
                {
                    _writersByAccountId.Remove(accountId);
                }
            }
            ConnectionChanged?.Invoke(false);
        }
    }

    /// <summary>Handles one incoming line. Returns the accountId when the
    /// message identifies one (agent.hello), so the caller can track which
    /// connection just closed.</summary>
    private string? Handle(string json, StreamWriter writer)
    {
        Mt5Message? message;
        try
        {
            message = Mt5WireParser.Parse(json);
        }
        catch
        {
            return null; // malformed frame: drop, never crash the gateway
        }

        switch (message)
        {
            case Mt5HelloMessage hello:
            {
                lock (_lock)
                {
                    _writersByAccountId[hello.AccountId] = writer;
                }
                Hello = hello;
                ConnectionChanged?.Invoke(true);
                EnvelopeReady?.Invoke(EventTypes.AgentConnected, new { agentId = hello.AgentId });
                return hello.AccountId;
            }
            case Mt5HeartbeatMessage heartbeat:
            {
                EnvelopeReady?.Invoke(EventTypes.AgentHeartbeat, new AgentHeartbeatPayload(heartbeat.AgentId, heartbeat.LatencyMs));
                return null;
            }
            case Mt5AckMessage ack:
            {
                var agentId = Hello?.AgentId ?? "mt5-execution-agent";
                var mapped = Mt5WireTranslator.ToCommandAck(ack, agentId);
                var type = mapped.Status is "accepted" or "duplicate"
                    ? EventTypes.ExecutionCommandAcknowledged
                    : EventTypes.ExecutionCommandRejected;
                EnvelopeReady?.Invoke(type, new CommandAckPayload(mapped));
                return null;
            }
            case Mt5ReportMessage report:
            {
                var agentId = Hello?.AgentId ?? "mt5-execution-agent";
                var mapped = Mt5WireTranslator.ToExecutionReport(report, agentId);
                // This build only ever reports SIMULATED — OrderSend does not
                // exist yet (EA-05 increment 6, pending explicit approval).
                var type = report.Status == "SIMULATED"
                    ? EventTypes.ExecutionOrderSimulated
                    : EventTypes.ExecutionCommandRejected;
                EnvelopeReady?.Invoke(type, new ExecutionReportPayload(mapped));
                return null;
            }
            default:
                return null; // unknown/unused types are ignored in this slice
        }
    }
}
