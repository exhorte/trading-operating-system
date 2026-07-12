using Dapper;
using Npgsql;

namespace TradingOs.Persistence;

/// <summary>
/// SentAt is a UTC DateTime on purpose: Npgsql materializes timestamptz as
/// DateTime (Kind=Utc), and Dapper's constructor mapping throws
/// InvalidCastException on a DateTimeOffset parameter — the exact bug that
/// made /api/audit/recent return 503 while writes worked (2026-07-12).
/// </summary>
public sealed record AuditEntry(string MessageId, string CorrelationId, string Type, string Source, DateTime SentAt);

/// <summary>
/// Minimal read proof for the slice (HTTP is allowed for exports/admin).
/// Real consumers (replay, P&L calendar, backtesting) arrive in Phase 11.
/// </summary>
public sealed class AuditRepository(string connectionString)
{
    public async Task<IReadOnlyList<AuditEntry>> RecentAsync(int limit, CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        var rows = await conn.QueryAsync<AuditEntry>(
            """
            SELECT message_id AS MessageId, correlation_id AS CorrelationId,
                   type AS Type, source AS Source, sent_at AS SentAt
            FROM envelopes ORDER BY sent_at DESC LIMIT @limit
            """,
            new { limit = Math.Clamp(limit, 1, 200) });
        return rows.ToList();
    }
}
