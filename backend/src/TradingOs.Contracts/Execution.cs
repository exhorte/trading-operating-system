using System.Text.Json;

namespace TradingOs.Contracts;

/// <summary>
/// Execution contracts — C# mirrors of lib/domain/execution.ts and the lean
/// wire commands in lib/contracts/mt5-wire.ts (Phase 09 observe bridge).
/// Only place_order is in this slice.
/// </summary>
public sealed record PlaceOrderCommand(
    string Kind,
    string CommandId,
    string AccountId,
    string AgentId,
    int ProtocolVersion,
    string RiskApprovalId,
    string ExpiresAt,
    string IssuedAt,
    string Symbol,
    string Side,
    string OrderType,
    double Volume,
    double? LimitPrice,
    double StopLoss,
    double TakeProfit,
    string? SignalId,
    string? StrategyId);

/// <summary>Mirror of domain CommandAck (statuses lowercase on the dashboard side).</summary>
public sealed record CommandAck(
    string CommandId,
    string AgentId,
    string Status,
    string? Reason,
    string ReceivedAt);

/// <summary>Mirror of the ExecutionReport read model (snapshots.ts slice).</summary>
public sealed record ExecutionReportView(
    string ReportId,
    string CommandId,
    string CorrelationId,
    string AccountId,
    string AgentId,
    string Symbol,
    string Side,
    string Status,
    string Detail,
    string ReportedAt);

/// <summary>
/// Typed rejection vocabulary (ADR 0010, EA-03) — mirror of
/// lib/contracts/execution/reject-reason.ts. Codes named in later fiches
/// (e.g. SYMBOL_MISMATCH) are documented in context/execution/protocol.md
/// but not added here until the gate that raises them exists.
/// </summary>
public static class CommandRejectCode
{
    public const string AccountMismatch = "ACCOUNT_MISMATCH";
    public const string ModeNotObserve = "MODE_NOT_OBSERVE";
    public const string AgentUnreachable = "AGENT_UNREACHABLE";
    public const string RiskNotApproved = "RISK_NOT_APPROVED";
}

public sealed record CommandRejection(string Code, string Detail);

public sealed record PlaceOrderCommandPayload(PlaceOrderCommand Command);

public sealed record CommandAckPayload(CommandAck Ack);

public sealed record ExecutionReportPayload(ExecutionReportView Report);

/// <summary>EA-06 dashboard read model for a resolved (or still-unresolved)
/// UNKNOWN commandId. Distinct from ExecutionReportView on purpose — see
/// Mt5ReconciledMessage's doc comment (mt5-wire.ts): a fill pieced together
/// after the fact must never be presented as one watched live.</summary>
public sealed record ReconciledView(
    string CommandId,
    string AccountId,
    string AgentId,
    string Outcome,
    string? Symbol,
    string? Side,
    string? BrokerOrderId,
    string? BrokerPositionId,
    double? FilledVolume,
    double? AveragePrice,
    string? BrokerRetcode,
    int Attempts,
    string Detail,
    string ReconciledAt);

public sealed record ReconciledPayload(ReconciledView Reconciled);

/// <summary>EA-06 dashboard read model for one open position exactly as the
/// terminal reports it right now (a PositionsTotal() scan).</summary>
public sealed record PositionScannedView(
    string AccountId,
    string AgentId,
    string BrokerPositionId,
    string Symbol,
    string Side,
    double Volume,
    int MagicNumber,
    bool IsExternal,
    string? KnownCommandId,
    string ScannedAt);

public sealed record PositionScannedPayload(PositionScannedView PositionScanned);

// --- lean wire (gateway → agent), mirrors Mt5OrderCommand in mt5-wire.ts ---

public sealed record Mt5OrderCommand(
    int Version,
    string Type,
    string AccountId,
    long Time,
    string Id,
    long ExpiresAt,
    string Symbol,
    string Side,
    string OrderType,
    double Volume,
    double? LimitPrice,
    double Sl,
    double Tp)
{
    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web);

    public string ToJson() => JsonSerializer.Serialize(this, Options);
}

// --- lean wire (agent → gateway), mirrors Mt5AckMessage / Mt5ReportMessage ---

public sealed record Mt5AckMessage(
    int Version, string Type, string AccountId, long Time,
    string CommandId, string Status, string? Reason)
    : Mt5Message(Version, Type, AccountId, Time);

public sealed record Mt5ReportMessage(
    int Version, string Type, string AccountId, long Time,
    string CommandId, string Status, string Symbol, string Side,
    string? BrokerOrderId, string? BrokerPositionId,
    double? FilledVolume, double? AveragePrice, string? BrokerRetcode, string Detail)
    : Mt5Message(Version, Type, AccountId, Time);

// --- EA-06 reconciliation (agent → gateway), mirrors mt5-wire.ts ---

/// <summary>Terminal resolution of a commandId left UNKNOWN — the state
/// machine's only legal exit from UNKNOWN is RECONCILED, so this is kept
/// distinct from Mt5ReportMessage rather than reusing its Status vocabulary.</summary>
public sealed record Mt5ReconciledMessage(
    int Version, string Type, string AccountId, long Time,
    string CommandId, string Outcome, string? Symbol, string? Side,
    string? BrokerOrderId, string? BrokerPositionId,
    double? FilledVolume, double? AveragePrice, string? BrokerRetcode,
    int Attempts, string Detail)
    : Mt5Message(Version, Type, AccountId, Time);

/// <summary>One open position observed directly from the terminal, sent one
/// per position (never batched — JsonLite.mqh parses flat objects only).
/// BrokerPositionId must come from POSITION_IDENTIFIER, never the ticket.</summary>
public sealed record Mt5PositionScannedMessage(
    int Version, string Type, string AccountId, long Time,
    string BrokerPositionId, string Symbol, string Side, double Volume,
    int MagicNumber, bool IsExternal, string? KnownCommandId)
    : Mt5Message(Version, Type, AccountId, Time);
