using System.Net.WebSockets;
using System.Text;
using TradingOs.Contracts;

namespace TradingOs.Gateway;

/// <summary>
/// WebSocket client that connects to the local MT5 observer producer
/// (tools/mt5-observer, ws://localhost:8765), parses lean wire messages,
/// translates them, updates GatewayState, and raises translated envelopes
/// for the host to broadcast.
///
/// Prototype-era note (ADR 0009): the observer is currently the WS *server*,
/// so the gateway dials out. The definitive MQL5 agent will invert this
/// (agent dials the gateway) per ADR 0005; only this class changes then.
/// Read-only: nothing is ever sent to the producer.
/// </summary>
public sealed class Mt5ObserverClient(GatewayState state, string url)
{
    private const int ReconnectDelayMs = 3_000;

    private ClientWebSocket? _socket;

    /// <summary>Translated envelope ready to broadcast (type + camelCase payload object).</summary>
    public event Action<string, object>? EnvelopeReady;

    /// <summary>Producer connection state changed (true = connected).</summary>
    public event Action<bool>? ConnectionChanged;

    /// <summary>True when a command can be delivered to the agent right now.</summary>
    public bool IsConnected => _socket is { State: WebSocketState.Open };

    /// <summary>
    /// Phase 09: send one lean command frame to the agent. The ONLY outbound
    /// path to the agent; the observe agent answers with ack/report and never
    /// touches the broker. Returns false when the agent is unreachable.
    /// </summary>
    public async Task<bool> SendCommandAsync(string json, CancellationToken ct)
    {
        var socket = _socket;
        if (socket is not { State: WebSocketState.Open })
        {
            return false;
        }
        try
        {
            var bytes = Encoding.UTF8.GetBytes(json);
            await socket.SendAsync(new ArraySegment<byte>(bytes), WebSocketMessageType.Text, true, ct);
            return true;
        }
        catch
        {
            return false;
        }
    }

    public async Task RunAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                using var socket = new ClientWebSocket();
                await socket.ConnectAsync(new Uri(url), ct);
                _socket = socket;
                ConnectionChanged?.Invoke(true);
                await ReceiveLoopAsync(socket, ct);
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch
            {
                // fall through to reconnect
            }

            _socket = null;
            ConnectionChanged?.Invoke(false);
            state.MarkAgentDisconnected();
            EnvelopeReady?.Invoke(EventTypes.AgentDisconnected, new { agentId = state.Hello?.AgentId ?? "mt5-observer" });
            try
            {
                await Task.Delay(ReconnectDelayMs, ct);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }
    }

    private async Task ReceiveLoopAsync(ClientWebSocket socket, CancellationToken ct)
    {
        var buffer = new byte[64 * 1024];
        var builder = new StringBuilder();

        while (socket.State == WebSocketState.Open && !ct.IsCancellationRequested)
        {
            builder.Clear();
            WebSocketReceiveResult result;
            do
            {
                result = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), ct);
                if (result.MessageType == WebSocketMessageType.Close)
                {
                    return;
                }
                builder.Append(Encoding.UTF8.GetString(buffer, 0, result.Count));
            } while (!result.EndOfMessage);

            Handle(builder.ToString());
        }
    }

    private void Handle(string json)
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

        switch (message)
        {
            case Mt5HelloMessage hello:
            {
                var agent = Mt5WireTranslator.ToAgentStatus(hello);
                state.SetHello(hello, agent);
                EnvelopeReady?.Invoke(EventTypes.AgentConnected, new { agentId = hello.AgentId });
                // T02a: resolve today's anchor immediately on connect too —
                // the periodic re-check (GatewayBridgeService) covers a day
                // rolling over without a fresh hello.
                var startsAtUtc = TradingDayAnchor.ResolveTodayStartUtc(
                    DateTimeOffset.UtcNow, hello.ServerUtcOffsetMinutes);
                EnvelopeReady?.Invoke(
                    EventTypes.RiskDayAnchorResolved,
                    new DayAnchorResolvedPayload(hello.AccountId, startsAtUtc.ToString("o")));
                break;
            }
            case Mt5AccountSnapshotMessage account:
            {
                var summary = Mt5WireTranslator.ToAccountSummary(account, state.Hello);
                state.SetAccount(summary);
                EnvelopeReady?.Invoke(EventTypes.AgentSnapshotAccount, new AccountSnapshotPayload(summary));
                break;
            }
            case Mt5PositionsSnapshotMessage positions:
            {
                var mapped = Mt5WireTranslator.ToPositions(positions, state.LastBid);
                state.SetPositions(mapped);
                EnvelopeReady?.Invoke(EventTypes.AgentSnapshotPositions, new PositionsSnapshotPayload(mapped));
                break;
            }
            // T05: server-side diff (mt5_observer.py::poll_positions) — direct
            // like agent.snapshot.account, never through the dashboard
            // PublishEvent whitelist. Replaces T02a's client-side detection.
            case Mt5PositionOpenedMessage opened:
            {
                var mapped = Mt5WireTranslator.ToPositionOpened(opened);
                EnvelopeReady?.Invoke(EventTypes.JournalPositionOpened, mapped);
                break;
            }
            // T02b: only the observer's deal history knows a position truly
            // closed — published direct like agent.snapshot.account, never
            // through the dashboard PublishEvent whitelist.
            case Mt5PositionClosedMessage closed:
            {
                var mapped = Mt5WireTranslator.ToTradeClosed(closed);
                EnvelopeReady?.Invoke(EventTypes.JournalTradeClosed, mapped);
                break;
            }
            case Mt5TickMessage tick:
            {
                state.SetTick(tick.Bid);
                EnvelopeReady?.Invoke(EventTypes.MarketTick, new MarketTickPayload(tick.Symbol, tick.Bid, tick.Ask));
                break;
            }
            case Mt5CandleMessage candle:
            {
                var mapped = Mt5WireTranslator.ToCandle(candle);
                state.AddCandle(candle.OpenTime, mapped);
                EnvelopeReady?.Invoke(EventTypes.MarketCandleClosed, new MarketCandlePayload(mapped));
                break;
            }
            case Mt5HeartbeatMessage heartbeat:
            {
                state.MarkAgentHeartbeat(heartbeat.LatencyMs, DateTimeOffset.UtcNow.ToString("o"));
                EnvelopeReady?.Invoke(EventTypes.AgentHeartbeat, new AgentHeartbeatPayload(heartbeat.AgentId, heartbeat.LatencyMs));
                break;
            }
            // Phase 09: agent receipts and SIMULATED outcomes flow back up.
            case Mt5AckMessage ack:
            {
                var agentId = state.Hello?.AgentId ?? "mt5-observer";
                var mapped = Mt5WireTranslator.ToCommandAck(ack, agentId);
                var type = mapped.Status is "accepted" or "duplicate"
                    ? EventTypes.ExecutionCommandAcknowledged
                    : EventTypes.ExecutionCommandRejected;
                EnvelopeReady?.Invoke(type, new CommandAckPayload(mapped));
                break;
            }
            case Mt5ReportMessage report when report.Status == "SIMULATED":
            {
                var agentId = state.Hello?.AgentId ?? "mt5-observer";
                var mapped = Mt5WireTranslator.ToExecutionReport(report, agentId);
                EnvelopeReady?.Invoke(EventTypes.ExecutionOrderSimulated, new ExecutionReportPayload(mapped));
                break;
            }
            default:
                break; // unknown/unused types are ignored in the observe slice
        }
    }
}
