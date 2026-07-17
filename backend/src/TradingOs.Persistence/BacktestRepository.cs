using Dapper;
using Npgsql;

namespace TradingOs.Persistence;

// timestamptz columns map to UTC DateTime (never DateTimeOffset) — see the
// AuditEntry lesson of 2026-07-12.
public sealed record BacktestRunRow(
    string RunId, string Symbol, string Timeframe, string EngineVersion, string Config,
    DateTime FromTime, DateTime ToTime, int CandleCount, int SignalCount, int ApprovedCount,
    int TradeCount, int WinCount, int LossCount, int TimeoutCount, int BothTouchCount,
    double WinRate, double AvgR, double ExpectancyR, int MaxConsecLosses, double CumulativeR,
    int OosTradeCount, DateTime CreatedAt);

public sealed record BacktestTradeRow(
    int Seq, DateTime SignalTime, string Side, double EntryPrice, double StopLoss,
    double TakeProfit, double Volume, string Outcome, bool BothTouch, double RMultiple,
    int BarsHeld, double ExitPrice, int Score, string Reason);

/// <summary>Read side for backtest results (HTTP export surface; runs are
/// produced by scripts/backtest.ts).</summary>
public sealed class BacktestRepository(string connectionString)
{
    // OOS LOCK (ADR 0013): while a refinement campaign is live, no displayed
    // aggregate may include the locked out-of-sample split — the stored
    // backtest_runs metrics are whole-period BY DESIGN (they are the record
    // read at --unlock-oos) and must never be rendered. All performance
    // figures below are therefore recomputed over the non-OOS trades in SQL,
    // so OOS-inclusive numbers never even reach the HTTP surface. Legacy runs
    // (split IS NULL, pre-Phase-12) predate the discipline and were already
    // fully read: their trades all count and OosTradeCount = 0.
    //
    // The formulas mirror lib/backtest/metrics.ts exactly (winRate/avgR over
    // DECIDED trades; expectancy over all; loss streaks count losses and
    // negative timeouts) — keep the two in sync.
    private const string RunSelect = """
        SELECT
          r.run_id AS RunId, r.symbol AS Symbol, r.timeframe AS Timeframe,
          r.engine_version AS EngineVersion, r.config::text AS Config,
          r.from_time AS FromTime, r.to_time AS ToTime, r.candle_count AS CandleCount,
          r.signal_count AS SignalCount, r.approved_count AS ApprovedCount,
          m.TradeCount, m.WinCount, m.LossCount, m.TimeoutCount, m.BothTouchCount,
          m.WinRate, m.AvgR, m.ExpectancyR, s.MaxConsecLosses, m.CumulativeR,
          m.OosTradeCount, r.created_at AS CreatedAt
        FROM backtest_runs r
        CROSS JOIN LATERAL (
          SELECT
            COUNT(*) FILTER (WHERE t.split IS NULL OR t.split <> 'oos')::int AS TradeCount,
            COUNT(*) FILTER (WHERE t.outcome = 'win' AND (t.split IS NULL OR t.split <> 'oos'))::int AS WinCount,
            COUNT(*) FILTER (WHERE t.outcome = 'loss' AND (t.split IS NULL OR t.split <> 'oos'))::int AS LossCount,
            COUNT(*) FILTER (WHERE t.outcome = 'timeout' AND (t.split IS NULL OR t.split <> 'oos'))::int AS TimeoutCount,
            COUNT(*) FILTER (WHERE t.both_touch AND (t.split IS NULL OR t.split <> 'oos'))::int AS BothTouchCount,
            COUNT(*) FILTER (WHERE t.split = 'oos')::int AS OosTradeCount,
            COALESCE(ROUND((100.0 * COUNT(*) FILTER (WHERE t.outcome = 'win' AND (t.split IS NULL OR t.split <> 'oos'))
              / NULLIF(COUNT(*) FILTER (WHERE t.outcome <> 'timeout' AND (t.split IS NULL OR t.split <> 'oos')), 0))::numeric, 2)::float8, 0) AS WinRate,
            COALESCE(ROUND((SUM(t.r_multiple) FILTER (WHERE t.outcome <> 'timeout' AND (t.split IS NULL OR t.split <> 'oos'))
              / NULLIF(COUNT(*) FILTER (WHERE t.outcome <> 'timeout' AND (t.split IS NULL OR t.split <> 'oos')), 0))::numeric, 2)::float8, 0) AS AvgR,
            COALESCE(ROUND((SUM(t.r_multiple) FILTER (WHERE t.split IS NULL OR t.split <> 'oos')
              / NULLIF(COUNT(*) FILTER (WHERE t.split IS NULL OR t.split <> 'oos'), 0))::numeric, 2)::float8, 0) AS ExpectancyR,
            COALESCE(ROUND(SUM(t.r_multiple) FILTER (WHERE t.split IS NULL OR t.split <> 'oos')::numeric, 2)::float8, 0) AS CumulativeR
          FROM backtest_trades t
          WHERE t.run_id = r.run_id
        ) m
        CROSS JOIN LATERAL (
          SELECT COALESCE(MAX(len), 0)::int AS MaxConsecLosses FROM (
            SELECT COUNT(*) AS len FROM (
              SELECT (t.outcome = 'loss' OR (t.outcome = 'timeout' AND t.r_multiple < 0)) AS is_loss,
                     t.seq - ROW_NUMBER() OVER (
                       PARTITION BY (t.outcome = 'loss' OR (t.outcome = 'timeout' AND t.r_multiple < 0))
                       ORDER BY t.seq) AS grp
              FROM backtest_trades t
              WHERE t.run_id = r.run_id AND (t.split IS NULL OR t.split <> 'oos')
            ) marked WHERE is_loss GROUP BY grp
          ) streaks
        ) s
        """;

    public async Task<IReadOnlyList<BacktestRunRow>> RunsAsync(CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        var rows = await conn.QueryAsync<BacktestRunRow>(
            $"{RunSelect} ORDER BY r.created_at DESC LIMIT 50");
        return rows.ToList();
    }

    public async Task<(BacktestRunRow? Run, IReadOnlyList<BacktestTradeRow> Trades)> RunAsync(
        string runId, CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        var run = await conn.QuerySingleOrDefaultAsync<BacktestRunRow>(
            $"{RunSelect} WHERE r.run_id = @runId", new { runId });
        if (run is null)
        {
            return (null, []);
        }
        // Individual OOS trades carry their R multiples (summable), so the
        // trade list itself is under the same lock — not just the aggregates.
        var trades = await conn.QueryAsync<BacktestTradeRow>(
            """
            SELECT seq AS Seq, signal_time AS SignalTime, side AS Side,
                   entry_price AS EntryPrice, stop_loss AS StopLoss, take_profit AS TakeProfit,
                   volume AS Volume, outcome AS Outcome, both_touch AS BothTouch,
                   r_multiple AS RMultiple, bars_held AS BarsHeld, exit_price AS ExitPrice,
                   score AS Score, reason AS Reason
            FROM backtest_trades
            WHERE run_id = @runId AND (split IS NULL OR split <> 'oos')
            ORDER BY seq
            """,
            new { runId });
        return (run, trades.ToList());
    }
}
