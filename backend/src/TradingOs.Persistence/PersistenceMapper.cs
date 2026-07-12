using System.Text.Json;

namespace TradingOs.Persistence;

/// <summary>One event drained from the channel, ready to persist.</summary>
public sealed record PersistedEvent(
    string MessageId,
    string CorrelationId,
    string Type,
    string Source,
    string SentAt,
    string PayloadJson);

// Typed rows mirroring schema.sql — extracted by the pure mapper, inserted by
// the writer. Kept as records so the mapping is unit-testable without a DB.
public sealed record CandleRow(string Symbol, string Timeframe, DateTimeOffset OpenTime, double Open, double High, double Low, double Close, double Volume, bool Closed);
public sealed record TickRow(string Symbol, DateTimeOffset Ts, double Bid, double Ask);
public sealed record SignalRow(string SignalId, string StrategyId, string Symbol, string Side, double EntryPrice, double StopLoss, double TakeProfit, int Score, int MaxScore, string Context, DateTimeOffset CreatedAt, DateTimeOffset ExpiresAt);
public sealed record DecisionRow(string ApprovalId, string SignalId, string AccountId, bool Approved, double? ApprovedVolume, string Reason, string GatesJson, DateTimeOffset DecidedAt);
public sealed record CommandRow(string CommandId, string? SignalId, string AccountId, string AgentId, string RiskApprovalId, string Symbol, string Side, string OrderType, double Volume, double StopLoss, double TakeProfit, DateTimeOffset IssuedAt, DateTimeOffset ExpiresAt);
public sealed record AckRow(string CommandId, string AgentId, string Status, string? Reason, DateTimeOffset ReceivedAt);
public sealed record ReportRow(string ReportId, string CommandId, string AccountId, string AgentId, string Symbol, string Side, string Status, string Detail, DateTimeOffset ReportedAt);

/// <summary>
/// Pure extraction: envelope payload JSON → typed row (null when the event
/// type has no typed table — it still lands in the envelopes audit table).
/// Payload shapes are the camelCase read models / payloads of lib/contracts.
/// </summary>
public static class PersistenceMapper
{
    public static object? ToTypedRow(string type, string payloadJson)
    {
        using var doc = JsonDocument.Parse(payloadJson);
        var root = doc.RootElement;
        return type switch
        {
            "market.candle.closed" => MapCandle(root.GetProperty("candle")),
            "market.tick" => MapTick(root),
            "strategy.signal.created" => MapSignal(root.GetProperty("signal")),
            "risk.decision.made" => MapDecision(root.GetProperty("decision")),
            "execution.command.place_order" => MapCommand(root.GetProperty("command")),
            "execution.command.acknowledged" or "execution.command.rejected" => MapAck(root.GetProperty("ack")),
            "execution.order.simulated" => MapReport(root.GetProperty("report")),
            _ => null,
        };
    }

    private static string Str(JsonElement e, string name) => e.GetProperty(name).GetString() ?? "";

    private static string? StrOrNull(JsonElement e, string name) =>
        e.TryGetProperty(name, out var p) && p.ValueKind != JsonValueKind.Null ? p.GetString() : null;

    private static double Num(JsonElement e, string name) => e.GetProperty(name).GetDouble();

    private static DateTimeOffset Time(JsonElement e, string name) =>
        DateTimeOffset.Parse(Str(e, name));

    private static CandleRow MapCandle(JsonElement c) => new(
        Str(c, "symbol"), Str(c, "timeframe"), Time(c, "openTime"),
        Num(c, "open"), Num(c, "high"), Num(c, "low"), Num(c, "close"),
        Num(c, "volume"), c.GetProperty("closed").GetBoolean());

    private static TickRow MapTick(JsonElement t) => new(
        Str(t, "symbol"), DateTimeOffset.UtcNow, Num(t, "bid"), Num(t, "ask"));

    private static SignalRow MapSignal(JsonElement s) => new(
        Str(s, "signalId"), Str(s, "strategyId"), Str(s, "symbol"), Str(s, "side"),
        Num(s, "entryPrice"), Num(s, "stopLoss"), Num(s, "takeProfit"),
        s.GetProperty("score").GetInt32(), s.GetProperty("maxScore").GetInt32(),
        Str(s, "contextSummary"), Time(s, "createdAt"), Time(s, "expiresAt"));

    private static DecisionRow MapDecision(JsonElement d) => new(
        Str(d, "approvalId"), Str(d, "signalId"), Str(d, "accountId"),
        d.GetProperty("approved").GetBoolean(),
        d.TryGetProperty("approvedVolume", out var v) && v.ValueKind == JsonValueKind.Number ? v.GetDouble() : null,
        Str(d, "reason"),
        d.TryGetProperty("gates", out var g) ? g.GetRawText() : "[]",
        Time(d, "decidedAt"));

    private static CommandRow MapCommand(JsonElement c) => new(
        Str(c, "commandId"), StrOrNull(c, "signalId"), Str(c, "accountId"), Str(c, "agentId"),
        Str(c, "riskApprovalId"), Str(c, "symbol"), Str(c, "side"), Str(c, "orderType"),
        Num(c, "volume"), Num(c, "stopLoss"), Num(c, "takeProfit"),
        Time(c, "issuedAt"), Time(c, "expiresAt"));

    private static AckRow MapAck(JsonElement a) => new(
        Str(a, "commandId"), Str(a, "agentId"), Str(a, "status"),
        StrOrNull(a, "reason"), Time(a, "receivedAt"));

    private static ReportRow MapReport(JsonElement r) => new(
        Str(r, "reportId"), Str(r, "commandId"), Str(r, "accountId"), Str(r, "agentId"),
        Str(r, "symbol"), Str(r, "side"), Str(r, "status"), Str(r, "detail"),
        Time(r, "reportedAt"));
}
