using Dapper;
using Npgsql;

namespace TradingOs.Persistence;

/// <summary>
/// T03: read + write for the `news_releases` cache. Deliberately outside the
/// envelope/PersistenceWriter pipeline (that pipeline maps one envelope to
/// one row; a calendar refresh replaces a whole release's future rows at
/// once) — same "standalone repository" shape as RiskTodayRepository.
/// </summary>
public sealed record NewsReleaseRow(int ReleaseId, string Label, DateTime ScheduledAt);

public sealed class NewsCalendarRepository(string connectionString)
{
    /// <summary>
    /// Every cached release strictly after `now`, soonest first — the news
    /// gate's only source of truth, and what /api/calendar/upcoming serves.
    /// Deliberately not account-scoped: the calendar is global.
    ///
    /// Returns null when the cache has NEVER been populated (the table is
    /// entirely empty) — distinct from a successful sync that currently has
    /// nothing upcoming (which returns an empty, non-null list). This
    /// distinction is the whole point of T03's fail-closed requirement: a
    /// fresh backend that hasn't completed its first FRED fetch yet must not
    /// be indistinguishable from "confirmed no releases soon".
    /// </summary>
    public async Task<IReadOnlyList<NewsReleaseRow>?> GetUpcomingOrNullAsync(DateTime now, CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);

        var everSynced = await conn.QuerySingleAsync<bool>("SELECT EXISTS(SELECT 1 FROM news_releases)");
        if (!everSynced)
        {
            return null;
        }

        var rows = await conn.QueryAsync<NewsReleaseRow>(
            """
            SELECT release_id AS ReleaseId, label AS Label, scheduled_at AS ScheduledAt
            FROM news_releases
            WHERE scheduled_at > @now
            ORDER BY scheduled_at ASC
            """,
            new { now });
        return rows.AsList();
    }

    /// <summary>
    /// Replaces every future row for one release with a freshly-fetched set,
    /// in one transaction — self-correcting for a FRED reschedule (the stale
    /// old date is gone, not left alongside the new one). Past rows are left
    /// untouched (harmless: GetUpcomingAsync already filters scheduled_at > now).
    /// </summary>
    public async Task ReplaceUpcomingAsync(
        int releaseId,
        string label,
        IReadOnlyList<DateTime> scheduledDates,
        DateTime now,
        CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);

        await conn.ExecuteAsync(
            "DELETE FROM news_releases WHERE release_id = @releaseId AND scheduled_at >= @now",
            new { releaseId, now }, tx);

        foreach (var scheduledAt in scheduledDates)
        {
            await conn.ExecuteAsync(
                """
                INSERT INTO news_releases (release_id, label, scheduled_at)
                VALUES (@releaseId, @label, @scheduledAt)
                ON CONFLICT (release_id, scheduled_at) DO NOTHING
                """,
                new { releaseId, label, scheduledAt }, tx);
        }

        await tx.CommitAsync(ct);
    }
}
