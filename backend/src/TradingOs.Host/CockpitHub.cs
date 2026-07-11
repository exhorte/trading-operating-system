using Microsoft.AspNetCore.SignalR;
using TradingOs.Contracts;
using TradingOs.Gateway;

namespace TradingOs.Host;

/// <summary>
/// Dashboard-facing SignalR hub (ADR 0005: SignalR is dashboard-side only).
/// Pattern: snapshot on connect via GetSnapshot, then "event" messages
/// carrying Envelope&lt;T&gt; (see dashboard_realtime_model.md).
/// </summary>
public sealed class CockpitHub(GatewayState state, Mt5ObserverClient observer) : Hub
{
    private const string Source = "cockpit-hub";

    /// <summary>Latest known state so a client can hydrate before the event stream.</summary>
    public CockpitSnapshotDto GetSnapshot() => state.Snapshot();

    /// <summary>
    /// Phase 09 command loop, observe-only. Broadcasts the command to every
    /// dashboard (single source of truth for the lifecycle), then flattens to
    /// the lean wire and forwards to the agent. Hard guard: the agent must be
    /// in observe mode — an absent/unknown mode is refused, never forwarded.
    /// </summary>
    public async Task SubmitCommand(PlaceOrderCommand command)
    {
        await Clients.All.SendAsync("event", Envelope<object>.Create(
            EventTypes.ExecutionCommandPlaceOrder,
            Source,
            new PlaceOrderCommandPayload(command),
            command.CommandId));

        var mode = state.Hello?.Mode;
        if (mode != "observe")
        {
            await RejectAsync(command, $"agent mode '{mode ?? "unknown"}' is not observe — command refused");
            return;
        }

        var lean = Mt5WireTranslator.FlattenPlaceOrder(command);
        var sent = await observer.SendCommandAsync(lean.ToJson(), CancellationToken.None);
        if (!sent)
        {
            await RejectAsync(command, "agent unreachable — command not delivered");
        }
    }

    private Task RejectAsync(PlaceOrderCommand command, string reason)
    {
        var ack = new CommandAck(
            CommandId: command.CommandId,
            AgentId: "gateway",
            Status: "rejected",
            Reason: reason,
            ReceivedAt: DateTimeOffset.UtcNow.ToString("o"));
        return Clients.All.SendAsync("event", Envelope<object>.Create(
            EventTypes.ExecutionCommandRejected,
            Source,
            new CommandAckPayload(ack),
            command.CommandId));
    }
}
