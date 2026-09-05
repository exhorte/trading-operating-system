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

public sealed record RiskTodaySummary(
    DateTime? DayAnchorStartsAtUtc,
    double? DayStartEquity,
    int TradesToday,
    ActiveLockoutRow? ActiveLockout);

public sealed class RiskTodayRepository(string connectionString)
{
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

        var activeLockout = await conn.QuerySingleOrDefaultAsync<ActiveLockoutRow>(
            """
            SELECT lockout_id AS LockoutId, reason AS Reason, since AS Since, until AS Until
            FROM risk_lockouts
            WHERE account_id = @accountId AND cleared_at IS NULL
            ORDER BY since DESC
            LIMIT 1
            """,
            new { accountId });

        return new RiskTodaySummary(
            anchor?.StartsAtUtc,
            anchor?.DayStartEquity,
            tradesToday,
            activeLockout);
    }
}
