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
    /// <summary>T05: Gateway-originated (server-side positions.snapshot diff)
    /// — moved off the PublishEvent whitelist; was client-detected in T02a.</summary>
    public const string JournalPositionOpened = "journal.position.opened";
    /// <summary>T02b: Gateway-originated — only the observer's deal history
    /// knows a real close happened, same category as RiskDayAnchorResolved
    /// (no PublishEvent whitelist entry).</summary>
    public const string JournalTradeClosed = "journal.trade_closed";
    /// <summary>T02c: Gateway-originated — emitted the instant a position
    /// opens while risk_lockouts already shows an active lock for the
    /// account (GatewayBridgeService.CheckLockoutViolationAsync), so a bypass
    /// is flagged live instead of only caught after the fact by T07's
    /// compliance detector. Best-effort against the persisted ledger; no
    /// PublishEvent whitelist entry, same category as JournalPositionOpened.</summary>
    public const string JournalLockoutViolated = "journal.lockout_violated";
    /// <summary>T03: Gateway-originated — the backend owns the FRED poll,
    /// broadcast on every refresh cycle regardless of whether the list
    /// changed (same idempotent-recheck pattern as RiskDayAnchorResolved).</summary>
    public const string MarketCalendarUpdated = "market.calendar.updated";
    /// <summary>T12 incrément 2: backend-originated — emitted by the HTTP
    /// endpoint that wrote the account settings ledger, never client-published
    /// (no PublishEvent whitelist entry): the anti-tilt rule is decided where
    /// the change is persisted, so a dashboard cannot announce one itself.</summary>
    public const string AccountsSettingsChanged = "accounts.settings.changed";
    /// <summary>EA-06: the state machine's UNKNOWN state resolving to
    /// RECONCILED — see Mt5ReconciledMessage's doc comment.</summary>
    public const string ExecutionReconciled = "execution.reconciled";
    /// <summary>EA-06: one open position as the terminal reports it right now
    /// (PositionsTotal() scan), agent-originated on the heartbeat cadence.</summary>
    public const string ExecutionPositionScan = "execution.position.scan";
    /// <summary>
    /// Whether the EA-05 execution agent's TCP connection is currently open
    /// (Mt5AgentServer.IsConnected). Deliberately NOT agent.connected: that
    /// one is also emitted by the read-only observer's hello, so it cannot
    /// answer "can an order actually reach MT5". Conflating the two is what
    /// made T09's connectionGate read the observer's link as execution
    /// readiness — see T09's fiche. Gateway-originated, no PublishEvent
    /// whitelist entry.
    /// </summary>
    public const string ExecutionAgentConnection = "execution.agent.connection";
}
