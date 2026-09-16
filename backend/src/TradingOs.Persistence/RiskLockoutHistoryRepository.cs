using Dapper;
using Npgsql;

namespace TradingOs.Persistence;

/// <summary>
/// T07 — read surface for GET /api/risk/lockouts: every lockout window that
/// could have been active up to a point in time, for the compliance
/// detectors (lib/compliance/violations.ts::detectLockoutViolation) to
/// evaluate per-trade. Distinct from RiskTodayRepository, which only ever
/// answers "is one active right now" — this answers "what were the windows,
/// historically", so the client can judge an arbitrary past openedAt.
///
/// Only an upper bound on `since` (not a precise interval overlap with the
/// caller's range): a lockout that started before the window can still
/// cover a trade inside it, and getting that overlap exactly right in SQL
/// buys nothing — detectLockoutViolation already does the precise per-trade
/// check client-side, so a little over-fetching here is simpler and
/// harmless (a personal system has a handful of lockouts, ever).
/// </summary>
public sealed record LockoutWindowRow(
    string LockoutId, string Reason, DateTime Since, DateTime? Until, DateTime? ClearedAt);

public sealed class RiskLockoutHistoryRepository(string connectionString)
{
    public async Task<IReadOnlyList<LockoutWindowRow>> GetUpToAsync(
        string accountId, DateTime toUtc, CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        var rows = await conn.QueryAsync<LockoutWindowRow>(
            """
            SELECT lockout_id AS LockoutId, reason AS Reason, since AS Since,
                   until AS Until, cleared_at AS ClearedAt
            FROM risk_lockouts
            WHERE account_id = @accountId AND since <= @toUtc
            ORDER BY since ASC
            """,
            new { accountId, toUtc });
        return rows.AsList();
    }
}
