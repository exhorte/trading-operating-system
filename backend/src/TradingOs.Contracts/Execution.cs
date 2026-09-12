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
