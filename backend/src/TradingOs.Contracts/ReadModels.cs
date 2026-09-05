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

/// <summary>T02a: the trading day's start, resolved from the MT5 terminal's
/// server-UTC offset — never a client-computed guess.</summary>
public sealed record DayAnchorResolvedPayload(string AccountId, string StartsAtUtc);

/// <summary>T02b: one position fully closed, as observed on the MT5 terminal —
/// RealizedPnl already sums every deal on the position (T02-lockout.md pitfall:
/// a single partial-close deal must never stand in for the net outcome).</summary>
public sealed record JournalTradeClosedPayload(
    string AccountId,
    string BrokerPositionId,
    string Symbol,
    string Side,
    double Volume,
    double RealizedPnl,
    string ClosedAt);

/// <summary>T03: one scheduled FRED release — mirrors lib/domain/risk.ts::UpcomingRelease.</summary>
public sealed record UpcomingRelease(int ReleaseId, string Label, string ScheduledAt);

/// <summary>T03: the full current upcoming list, always a replace, never a
/// delta. Null means the cache has never been populated (see
/// NewsCalendarRepository.GetUpcomingOrNullAsync) — the client's news gate
/// must fail closed on null, never treat it as "confirmed empty".</summary>
public sealed record CalendarUpdatedPayload(UpcomingRelease[]? Releases);

/// <summary>Initial state a dashboard receives on hub connect (snapshot + events pattern).</summary>
public sealed record CockpitSnapshotDto(
    AccountSummary? Account,
    Position[] Positions,
    AgentStatus[] Agents,
    Candle[] Candles);
