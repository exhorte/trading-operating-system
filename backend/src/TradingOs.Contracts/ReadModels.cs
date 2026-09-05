namespace TradingOs.Contracts;

/// <summary>
/// Dashboard read models — C# mirrors of lib/contracts/snapshots.ts (the slice
/// used by the observe path). Serialized camelCase so the TS store consumes
/// them unchanged.
/// </summary>
public sealed record AccountSummary(
    string AccountId,
    string Label,
    string Broker,
    string Currency,
    double Balance,
    double Equity,
    double DailyPnl,
    double DailyDrawdownPercent,
    double TotalDrawdownPercent,
    double OpenRiskPercent);

public sealed record Position(
    string PositionId,
    string AccountId,
    string Symbol,
    string Side,
    double Volume,
    double EntryPrice,
    double CurrentPrice,
    double StopLoss,
    double TakeProfit,
    double UnrealizedPnl,
    double RMultiple,
    string StrategyId,
    string OpenedAt);

public sealed record AgentStatus(
    string AgentId,
    string AccountId,
    string Platform,
    string State,
    double LatencyMs,
    string LastHeartbeatAt,
    string Version);

/// <summary>Domain candle mirror (lib/domain/market.ts) relayed to the dashboard engine.</summary>
public sealed record Candle(
    string Symbol,
    string Timeframe,
    string OpenTime,
    double Open,
    double High,
    double Low,
    double Close,
    double Volume,
    bool Closed);

// --- event payloads (lib/contracts/events.ts slice) ---

public sealed record MarketTickPayload(string Symbol, double Bid, double Ask);

public sealed record MarketCandlePayload(Candle Candle);

public sealed record AgentHeartbeatPayload(string AgentId, double LatencyMs);

public sealed record AccountSnapshotPayload(AccountSummary Account);

public sealed record PositionsSnapshotPayload(Position[] Positions);

/// <summary>Initial state a dashboard receives on hub connect (snapshot + events pattern).</summary>
public sealed record CockpitSnapshotDto(
    AccountSummary? Account,
    Position[] Positions,
    AgentStatus[] Agents,
    Candle[] Candles);
