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
    DateTime CreatedAt);

public sealed record BacktestTradeRow(
    int Seq, DateTime SignalTime, string Side, double EntryPrice, double StopLoss,
    double TakeProfit, double Volume, string Outcome, bool BothTouch, double RMultiple,
    int BarsHeld, double ExitPrice, int Score, string Reason);

/// <summary>Read side for backtest results (HTTP export surface; runs are
/// produced by scripts/backtest.ts).</summary>
public sealed class BacktestRepository(string connectionString)
{
    private const string RunColumns = """
        run_id AS RunId, symbol AS Symbol, timeframe AS Timeframe,
        engine_version AS EngineVersion, config::text AS Config,
        from_time AS FromTime, to_time AS ToTime, candle_count AS CandleCount,
        signal_count AS SignalCount, approved_count AS ApprovedCount,
        trade_count AS TradeCount, win_count AS WinCount, loss_count AS LossCount,
        timeout_count AS TimeoutCount, both_touch_count AS BothTouchCount,
        win_rate AS WinRate, avg_r AS AvgR, expectancy_r AS ExpectancyR,
        max_consec_losses AS MaxConsecLosses, cumulative_r AS CumulativeR,
        created_at AS CreatedAt
        """;

    public async Task<IReadOnlyList<BacktestRunRow>> RunsAsync(CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        var rows = await conn.QueryAsync<BacktestRunRow>(
            $"SELECT {RunColumns} FROM backtest_runs ORDER BY created_at DESC LIMIT 50");
        return rows.ToList();
    }

    public async Task<(BacktestRunRow? Run, IReadOnlyList<BacktestTradeRow> Trades)> RunAsync(
        string runId, CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        var run = await conn.QuerySingleOrDefaultAsync<BacktestRunRow>(
            $"SELECT {RunColumns} FROM backtest_runs WHERE run_id = @runId", new { runId });
        if (run is null)
        {
            return (null, []);
        }
        var trades = await conn.QueryAsync<BacktestTradeRow>(
            """
            SELECT seq AS Seq, signal_time AS SignalTime, side AS Side,
                   entry_price AS EntryPrice, stop_loss AS StopLoss, take_profit AS TakeProfit,
                   volume AS Volume, outcome AS Outcome, both_touch AS BothTouch,
                   r_multiple AS RMultiple, bars_held AS BarsHeld, exit_price AS ExitPrice,
                   score AS Score, reason AS Reason
            FROM backtest_trades WHERE run_id = @runId ORDER BY seq
            """,
            new { runId });
        return (run, trades.ToList());
    }
}
