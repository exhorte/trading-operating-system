namespace TradingOs.Contracts;

/// <summary>
/// Realtime message envelope — C# mirror of lib/contracts/envelope.ts
/// (canonical schema source per ADR 0004; divergence is a defect).
/// Serialized camelCase on the wire.
/// </summary>
public sealed record Envelope<TPayload>(
    string MessageId,
    string CorrelationId,
    string? CausationId,
    string Type,
    int SchemaVersion,
    string Source,
    string Target,
    string SentAt,
    TPayload Payload)
{
    public static Envelope<TPayload> Create(string type, string source, TPayload payload, string? correlationId = null)
    {
        var id = Guid.NewGuid().ToString();
        return new Envelope<TPayload>(
            MessageId: id,
            CorrelationId: correlationId ?? id,
            CausationId: null,
            Type: type,
            SchemaVersion: 1,
            Source: source,
            Target: "dashboard",
            SentAt: DateTimeOffset.UtcNow.ToString("o"),
            Payload: payload);
    }
}

/// <summary>Event type constants used by this slice (subset of the TS EventType union).</summary>
public static class EventTypes
{
    public const string MarketTick = "market.tick";
    public const string MarketCandleClosed = "market.candle.closed";
    public const string AgentConnected = "agent.connected";
    public const string AgentHeartbeat = "agent.heartbeat";
    public const string AgentDisconnected = "agent.disconnected";
    public const string AgentSnapshotAccount = "agent.snapshot.account";
    public const string AgentSnapshotPositions = "agent.snapshot.positions";
    public const string ExecutionCommandPlaceOrder = "execution.command.place_order";
    public const string ExecutionCommandAcknowledged = "execution.command.acknowledged";
    public const string ExecutionCommandRejected = "execution.command.rejected";
    public const string ExecutionOrderSimulated = "execution.order.simulated";
    /// <summary>T02a: Gateway-originated (needs the MT5 terminal's server-time
    /// offset), never client-published — no PublishEvent whitelist entry.</summary>
    public const string RiskDayAnchorResolved = "risk.day_anchor.resolved";
    /// <summary>T02b: Gateway-originated — only the observer's deal history
    /// knows a real close happened, same category as RiskDayAnchorResolved
    /// (no PublishEvent whitelist entry).</summary>
    public const string JournalTradeClosed = "journal.trade_closed";
    /// <summary>T03: Gateway-originated — the backend owns the FRED poll,
    /// broadcast on every refresh cycle regardless of whether the list
    /// changed (same idempotent-recheck pattern as RiskDayAnchorResolved).</summary>
    public const string MarketCalendarUpdated = "market.calendar.updated";
}
