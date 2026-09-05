using Dapper;
using Npgsql;

namespace TradingOs.Persistence;

/// <summary>
/// T02a hydration read: what a freshly (re)connected dashboard needs to show
/// the right numbers immediately, before the live event stream catches up —
/// today's anchor, the real trade count since it, and any active lockout.
/// Minimal read proof (ADR 0003: HTTP is fine for this, not for trading flow).
/// </summary>
public sealed record ActiveLockoutRow(string LockoutId, string Reason, DateTime Since, DateTime? Until);

/// <summary>T02b: one closed trade, most-recent-first — enough to derive the
/// consecutive-loss streak without a recursive query.</summary>
public sealed record ClosedTradeStreakRow(double RealizedPnl, DateTime ClosedAt);

public sealed record RiskTodaySummary(
    DateTime? DayAnchorStartsAtUtc,
    double? DayStartEquity,
    int TradesToday,
    int ConsecutiveLosses,
    DateTime? LastConsecutiveLossAt,
    ActiveLockoutRow? ActiveLockout);

public sealed class RiskTodayRepository(string connectionString)
{
    /// <summary>Bound on how far back to look — no real trader runs a losing
    /// streak anywhere near this long; keeps the query a plain LIMIT scan.</summary>
    private const int MaxRecentClosedTrades = 50;

    public async Task<RiskTodaySummary> GetAsync(string accountId, CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);

        var anchor = await conn.QuerySingleOrDefaultAsync<(DateTime StartsAtUtc, double? DayStartEquity)?>(
            """
            SELECT starts_at_utc AS StartsAtUtc, day_start_equity AS DayStartEquity
            FROM trading_day_anchors
            WHERE account_id = @accountId
            ORDER BY starts_at_utc DESC
            LIMIT 1
            """,
            new { accountId });

        var tradesToday = anchor is null
            ? 0
            : await conn.QuerySingleAsync<int>(
                """
                SELECT count(*) FROM position_opens
                WHERE account_id = @accountId AND opened_at >= @startsAtUtc
                """,
                new { accountId, anchor.Value.StartsAtUtc });

        // T02b: consecutive losses never reset at the day anchor (a losing
        // streak spanning midnight is still a streak) — no date filter here.
        var recentClosed = await conn.QueryAsync<ClosedTradeStreakRow>(
            """
            SELECT realized_pnl AS RealizedPnl, closed_at AS ClosedAt
            FROM closed_trades
            WHERE account_id = @accountId
            ORDER BY closed_at DESC
            LIMIT @limit
            """,
            new { accountId, limit = MaxRecentClosedTrades });
        var (consecutiveLosses, lastConsecutiveLossAt) = CountConsecutiveLosses(recentClosed);

        // T02b: an expired timed pause must not read back as "active" right
        // after expiry — the client's own expiry publish (risk.lockout.cleared,
        // clearedBy "pause-expired") is the primary path, this is the backup.
        var activeLockout = await conn.QuerySingleOrDefaultAsync<ActiveLockoutRow>(
            """
            SELECT lockout_id AS LockoutId, reason AS Reason, since AS Since, until AS Until
            FROM risk_lockouts
            WHERE account_id = @accountId AND cleared_at IS NULL
              AND (until IS NULL OR until > now())
            ORDER BY since DESC
            LIMIT 1
            """,
            new { accountId });

        return new RiskTodaySummary(
            anchor?.StartsAtUtc,
            anchor?.DayStartEquity,
            tradesToday,
            consecutiveLosses,
            lastConsecutiveLossAt,
            activeLockout);
    }

    /// <summary>Trailing run of losses from the most recent trade backward,
    /// stopping at the first non-losing trade. Pure — testable without a DB.</summary>
    public static (int Count, DateTime? LastLossAt) CountConsecutiveLosses(
        IEnumerable<ClosedTradeStreakRow> mostRecentFirst)
    {
        var count = 0;
        DateTime? lastLossAt = null;
        foreach (var trade in mostRecentFirst)
        {
            if (trade.RealizedPnl >= 0)
            {
                break;
            }
            count++;
            lastLossAt ??= trade.ClosedAt;
        }
        return (count, lastLossAt);
    }
}
