using System.Text.Json;

namespace TradingOs.Contracts;

/// <summary>
/// Lean MT5 edge wire — C# mirror of lib/contracts/mt5-wire.ts (ADR 0005).
/// Flat fields, epoch-ms time, uppercase side. The gateway translates these
/// into Envelope&lt;T&gt; + read models; nothing else may consume them.
/// </summary>
public abstract record Mt5Message(int Version, string Type, string AccountId, long Time);

/// <remarks>I1 (2026-09-26): the parameters after ServerUtcOffsetMinutes
/// come from the execution agent only (the Python observer sends none of
/// them, so they stay null for it). The agent's hello also carries a
/// "token", deliberately absent from this record: Mt5AgentServer checks it
/// on the raw line, and it is never kept, logged or persisted.</remarks>
public sealed record Mt5HelloMessage(
    int Version, string Type, string AccountId, long Time,
    string AgentId, string Symbol, string Broker, string Server,
    string[] OrderTypes, double MinVolume, double MaxVolume, double VolumeStep,
    string FillingMode, int StopsLevelPoints, string Mode, string AgentVersion,
    int ServerUtcOffsetMinutes,
    string[]? Capabilities = null, string? BuildId = null, string? ModeCeiling = null,
    string? Identity = null, string? ExpectedAccountId = null, string? TradeMode = null,
    string? MarginMode = null, bool? FifoClose = null, int? Leverage = null, string? Currency = null,
    bool? TerminalTradeAllowed = null, bool? ExpertTradeAllowed = null,
    bool? AccountTradeExpert = null, bool? AccountTradeAllowed = null,
    bool? Tradable = null, bool? Closable = null, bool? Halted = null,
    string[]? AttachedExperts = null)
    : Mt5Message(Version, Type, AccountId, Time);

/// <remarks>I1: what can change while an execution agent is connected —
/// Algo Trading clicked, another EA attached, the halt set on the chart.
/// Null for the observer's heartbeats.</remarks>
public sealed record Mt5HeartbeatMessage(
    int Version, string Type, string AccountId, long Time,
    string AgentId, double LatencyMs,
    string? Mode = null, string? Identity = null,
    bool? TerminalTradeAllowed = null, bool? ExpertTradeAllowed = null,
    bool? AccountTradeExpert = null, bool? AccountTradeAllowed = null,
    bool? Halted = null, long? GatewaySilentMs = null, string[]? AttachedExperts = null)
    : Mt5Message(Version, Type, AccountId, Time);

public sealed record Mt5TickMessage(
    int Version, string Type, string AccountId, long Time,
    string Symbol, double Bid, double Ask)
    : Mt5Message(Version, Type, AccountId, Time);

public sealed record Mt5CandleMessage(
    int Version, string Type, string AccountId, long Time,
    string Symbol, string Timeframe, long OpenTime,
    double Open, double High, double Low, double Close, double Volume, bool Closed)
    : Mt5Message(Version, Type, AccountId, Time);

public sealed record Mt5AccountSnapshotMessage(
    int Version, string Type, string AccountId, long Time,
    double Balance, double Equity, double Margin, double FreeMargin, string Currency)
    : Mt5Message(Version, Type, AccountId, Time);

public sealed record Mt5PositionSnapshot(
    string BrokerPositionId, string Symbol, string Side, double Volume,
    double EntryPrice, double StopLoss, double TakeProfit, double FloatingPnl);

public sealed record Mt5PositionsSnapshotMessage(
    int Version, string Type, string AccountId, long Time,
    Mt5PositionSnapshot[] Positions)
    : Mt5Message(Version, Type, AccountId, Time);

/// <summary>T05: observer-detected new position (server-side diff, replaces
/// the old client-side T02a detection).</summary>
public sealed record Mt5PositionOpenedMessage(
    int Version, string Type, string AccountId, long Time,
    string BrokerPositionId, string Symbol, string Side, double Volume,
    double EntryPrice, double StopLoss, double TakeProfit, long OpenedAt)
    : Mt5Message(Version, Type, AccountId, Time);

/// <summary>T02b: observer-detected closed position — realizedPnl is already
/// summed over every deal on the position (entry + all partial exits).
/// ExitPrice (T05) is the volume-weighted average across every exit deal.</summary>
public sealed record Mt5PositionClosedMessage(
    int Version, string Type, string AccountId, long Time,
    string BrokerPositionId, string Symbol, string Side, double Volume,
    double RealizedPnl, double ExitPrice, long ClosedAt)
    : Mt5Message(Version, Type, AccountId, Time);

/// <summary>Parses one lean wire JSON message by its "type" discriminator.</summary>
public static class Mt5WireParser
{
    private static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web);

    public static Mt5Message? Parse(string json)
    {
        using var doc = JsonDocument.Parse(json);
        if (!doc.RootElement.TryGetProperty("type", out var typeProp))
        {
            return null;
        }

        var type = typeProp.GetString();
        return type switch
        {
            "agent.hello" => doc.RootElement.Deserialize<Mt5HelloMessage>(Options),
            "agent.heartbeat" => doc.RootElement.Deserialize<Mt5HeartbeatMessage>(Options),
            "market.tick" => doc.RootElement.Deserialize<Mt5TickMessage>(Options),
            "market.candle" => doc.RootElement.Deserialize<Mt5CandleMessage>(Options),
            "account.snapshot" => doc.RootElement.Deserialize<Mt5AccountSnapshotMessage>(Options),
            "positions.snapshot" => doc.RootElement.Deserialize<Mt5PositionsSnapshotMessage>(Options),
            "position.opened" => doc.RootElement.Deserialize<Mt5PositionOpenedMessage>(Options),
            "position.closed" => doc.RootElement.Deserialize<Mt5PositionClosedMessage>(Options),
            // Phase 09: command receipts and SIMULATED outcomes from the agent.
            "execution.ack" => doc.RootElement.Deserialize<Mt5AckMessage>(Options),
            "execution.report" => doc.RootElement.Deserialize<Mt5ReportMessage>(Options),
            // EA-06: UNKNOWN resolution and terminal position scans.
            "execution.reconciled" => doc.RootElement.Deserialize<Mt5ReconciledMessage>(Options),
            "execution.position.scan" => doc.RootElement.Deserialize<Mt5PositionScannedMessage>(Options),
            _ => null,
        };
    }
}
