using Dapper;
using Npgsql;

namespace TradingOs.Persistence;

/// <summary>
/// T05 — writes and reads the immutable capture-fact rows (see schema.sql).
/// Deliberately outside the envelope/PersistenceWriter pipeline: that
/// pipeline maps one envelope to one row, but writing an 'entry' row needs no
/// lookup while writing an 'exit' row needs to read the matching 'entry' row
/// first (to reuse its window_start_utc/entry_price/stop_loss/take_profit) —
/// a two-step operation the generic mapper isn't shaped for. Same
/// "standalone repository" pattern as RiskTodayRepository/NewsCalendarRepository.
/// </summary>
public sealed record TradeCaptureFact(
    string AccountId,
    string BrokerPositionId,
    string Kind,
    string Symbol,
    string Timeframe,
    DateTime WindowStartUtc,
    DateTime WindowEndUtc,
    double EntryPrice,
    double StopLoss,
    double TakeProfit,
    double? ExitPrice,
    DateTime CapturedAt);

public sealed class TradeCaptureRepository(string connectionString)
{
    /// <summary>How far before the entry the rendered window reaches back —
    /// enough bars for session structure/liquidity/FVGs to be visible.
    /// Fixed for now; a per-symbol/session-anchored window is a later
    /// refinement, not needed for T05's success criterion.</summary>
    public static readonly TimeSpan Lookback = TimeSpan.FromHours(6);

    /// <summary>
    /// Written once, at journal.position.opened. Idempotent against a
    /// reconnect replay (ON CONFLICT DO NOTHING) — the row is immutable by
    /// design, so a duplicate write must never overwrite it.
    /// </summary>
    public async Task RecordEntryAsync(
        string accountId,
        string brokerPositionId,
        string symbol,
        string timeframe,
        DateTime openedAtUtc,
        double entryPrice,
        double stopLoss,
        double takeProfit,
        CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        await conn.ExecuteAsync(
            """
            INSERT INTO trade_captures
                (account_id, broker_position_id, kind, symbol, timeframe,
                 window_start_utc, window_end_utc, entry_price, stop_loss, take_profit,
                 exit_price, captured_at)
            VALUES
                (@accountId, @brokerPositionId, 'entry', @symbol, @timeframe,
                 @windowStart, @openedAtUtc, @entryPrice, @stopLoss, @takeProfit,
                 NULL, @openedAtUtc)
            ON CONFLICT (account_id, broker_position_id, kind) DO NOTHING
            """,
            new
            {
                accountId,
                brokerPositionId,
                symbol,
                timeframe,
                windowStart = openedAtUtc - Lookback,
                openedAtUtc,
                entryPrice,
                stopLoss,
                takeProfit,
            });
    }

    /// <summary>
    /// Written once, at journal.trade_closed. Reuses the matching 'entry'
    /// row's window_start_utc/entry_price/stop_loss/take_profit — the exit
    /// capture shows the same pre-entry context plus the full trade
    /// duration. Silently no-ops when no entry row exists (a position this
    /// backend never saw open — e.g. it predates this feature): there is no
    /// window to anchor an exit capture to, and inventing one would violate
    /// the non-anticipation guarantee this table exists to provide.
    /// </summary>
    public async Task RecordExitAsync(
        string accountId,
        string brokerPositionId,
        double exitPrice,
        DateTime closedAtUtc,
        CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);

        var entry = await conn.QuerySingleOrDefaultAsync<TradeCaptureFact>(
            """
            SELECT account_id AS AccountId, broker_position_id AS BrokerPositionId, kind AS Kind,
                   symbol AS Symbol, timeframe AS Timeframe,
                   window_start_utc AS WindowStartUtc, window_end_utc AS WindowEndUtc,
                   entry_price AS EntryPrice, stop_loss AS StopLoss, take_profit AS TakeProfit,
                   exit_price AS ExitPrice, captured_at AS CapturedAt
            FROM trade_captures
            WHERE account_id = @accountId AND broker_position_id = @brokerPositionId AND kind = 'entry'
            """,
            new { accountId, brokerPositionId });
        if (entry is null)
        {
            return;
        }

        await conn.ExecuteAsync(
            """
            INSERT INTO trade_captures
                (account_id, broker_position_id, kind, symbol, timeframe,
                 window_start_utc, window_end_utc, entry_price, stop_loss, take_profit,
                 exit_price, captured_at)
            VALUES
                (@accountId, @brokerPositionId, 'exit', @symbol, @timeframe,
                 @windowStart, @closedAtUtc, @entryPrice, @stopLoss, @takeProfit,
                 @exitPrice, @closedAtUtc)
            ON CONFLICT (account_id, broker_position_id, kind) DO NOTHING
            """,
            new
            {
                accountId,
                brokerPositionId,
                symbol = entry.Symbol,
                timeframe = entry.Timeframe,
                windowStart = entry.WindowStartUtc,
                closedAtUtc,
                entryPrice = entry.EntryPrice,
                stopLoss = entry.StopLoss,
                takeProfit = entry.TakeProfit,
                exitPrice,
            });
    }

    /// <summary>Read surface for GET /api/captures/{brokerPositionId}.</summary>
    public async Task<(TradeCaptureFact? Entry, TradeCaptureFact? Exit)> GetAsync(
        string accountId, string brokerPositionId, CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        var rows = await conn.QueryAsync<TradeCaptureFact>(
            """
            SELECT account_id AS AccountId, broker_position_id AS BrokerPositionId, kind AS Kind,
                   symbol AS Symbol, timeframe AS Timeframe,
                   window_start_utc AS WindowStartUtc, window_end_utc AS WindowEndUtc,
                   entry_price AS EntryPrice, stop_loss AS StopLoss, take_profit AS TakeProfit,
                   exit_price AS ExitPrice, captured_at AS CapturedAt
            FROM trade_captures
            WHERE account_id = @accountId AND broker_position_id = @brokerPositionId
            """,
            new { accountId, brokerPositionId });
        var list = rows.AsList();
        return (
            list.FirstOrDefault(r => r.Kind == "entry"),
            list.FirstOrDefault(r => r.Kind == "exit"));
    }
}
