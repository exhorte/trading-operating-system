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

    /// <summary>Translated envelope ready to broadcast (type + camelCase payload object).</summary>
    public event Action<string, object>? EnvelopeReady;

    /// <summary>Producer connection state changed (true = connected).</summary>
    public event Action<bool>? ConnectionChanged;

    public async Task RunAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                using var socket = new ClientWebSocket();
                await socket.ConnectAsync(new Uri(url), ct);
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
            default:
                break; // unknown/unused types are ignored in the observe slice
        }
    }
}
