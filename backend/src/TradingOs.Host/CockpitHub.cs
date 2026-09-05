using System.Text.Json;
using Microsoft.AspNetCore.SignalR;
using TradingOs.Contracts;
using TradingOs.Gateway;
using TradingOs.Persistence;

namespace TradingOs.Host;

/// <summary>
/// Dashboard-facing SignalR hub (ADR 0005: SignalR is dashboard-side only).
/// Pattern: snapshot on connect via GetSnapshot, then "event" messages
/// carrying Envelope&lt;T&gt; (see dashboard_realtime_model.md).
/// </summary>
public sealed class CockpitHub(GatewayState state, Mt5ObserverClient observer, PersistenceWriter writer) : Hub
{
    private const string Source = "cockpit-hub";

    /// <summary>Strict whitelist for client-published events (Phase 10, extended
    /// by T04/T02a). Anything else is refused — dashboards may publish exactly
    /// these facts. Note: risk.day_anchor.resolved is NOT here — it needs the
    /// MT5 terminal's offset, so only the Gateway ever produces it.</summary>
    private static readonly HashSet<string> PublishableTypes =
        [
            "strategy.signal.created",
            "risk.decision.made",
            "journal.ticket.created",
            "risk.day_anchor.equity_observed",
            "journal.position.opened",
            "risk.lockout.enabled",
            "risk.lockout.cleared",
            "risk.lockout.acknowledged",
        ];

    private const int MaxPublishBytes = 64 * 1024;

    /// <summary>Latest known state so a client can hydrate before the event stream.</summary>
    public CockpitSnapshotDto GetSnapshot() => state.Snapshot();

    /// <summary>
    /// Phase 10: a dashboard publishes a signal/decision envelope; the hub
    /// persists it and rebroadcasts to every dashboard — making the hub the
    /// single source of truth for the signal flow (multi-tab consistent).
    /// </summary>
    public async Task PublishEvent(JsonElement envelope)
    {
        if (envelope.GetRawText().Length > MaxPublishBytes)
        {
            return;
        }
        if (!envelope.TryGetProperty("type", out var typeProp) ||
            typeProp.GetString() is not { } type ||
            !PublishableTypes.Contains(type))
        {
            return; // not on the whitelist: refuse silently, never rebroadcast
        }

        await Clients.All.SendAsync("event", envelope);

        writer.Enqueue(new PersistedEvent(
            MessageId: GetString(envelope, "messageId") ?? Guid.NewGuid().ToString(),
            CorrelationId: GetString(envelope, "correlationId") ?? "",
            Type: type,
            Source: GetString(envelope, "source") ?? "dashboard",
            SentAt: GetString(envelope, "sentAt") ?? DateTimeOffset.UtcNow.ToString("o"),
            PayloadJson: envelope.TryGetProperty("payload", out var payload)
                ? payload.GetRawText()
                : "{}"));
    }

    private static string? GetString(JsonElement e, string name) =>
        e.TryGetProperty(name, out var p) && p.ValueKind == JsonValueKind.String ? p.GetString() : null;

    /// <summary>
    /// Phase 09 command loop, observe-only. Broadcasts the command to every
    /// dashboard (single source of truth for the lifecycle), then flattens to
    /// the lean wire and forwards to the agent. Hard guard: the agent must be
    /// in observe mode — an absent/unknown mode is refused, never forwarded.
    /// </summary>
    public async Task SubmitCommand(PlaceOrderCommand command)
    {
        var issued = Envelope<object>.Create(
            EventTypes.ExecutionCommandPlaceOrder,
            Source,
            new PlaceOrderCommandPayload(command),
            command.CommandId);
        await Clients.All.SendAsync("event", issued);
        GatewayBridgeService.Persist(writer, issued);

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
        var envelope = Envelope<object>.Create(
            EventTypes.ExecutionCommandRejected,
            Source,
            new CommandAckPayload(ack),
            command.CommandId);
        GatewayBridgeService.Persist(writer, envelope);
        return Clients.All.SendAsync("event", envelope);
    }
}
