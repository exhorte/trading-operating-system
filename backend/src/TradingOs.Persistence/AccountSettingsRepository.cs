using System.Text.Json;
using Dapper;
using Npgsql;

namespace TradingOs.Persistence;

/// <summary>
/// One row of the account settings ledger (schema.sql, account_settings).
/// DayStartedSince: a trading-day anchor — on any account — has started after
/// this change was requested. A deferred change is in effect for the account
/// being traded once *its* anchor is newer than RequestedAt (resolved
/// client-side, lib/accounts/settings.ts); this flag is the conservative,
/// all-accounts version of that fact, used to refuse cancelling a change
/// that may already have governed a session.
/// </summary>
public sealed record AccountSettingsRow(
    string VersionId,
    string Firm,
    string SettingsJson,
    DateTime RequestedAt,
    bool Deferred,
    string DeferralReasonsJson,
    DateTime? CancelledAt,
    bool DayStartedSince);

public enum CancelOutcome
{
    Cancelled,
    NotFound,
    NotDeferred,
    AlreadyCancelled,
    AlreadyInEffect,
}

/// <summary>
/// T12 incrément 2 — persistence of the Settings screen: the append-only
/// ledger, and the facts AccountSettingsGuard needs from the database (trades
/// since each account's day anchor, active lockouts). Same queries as
/// RiskTodayRepository, widened to every account — see AccountSettingsGuard
/// for why one account is not enough.
/// </summary>
public sealed class AccountSettingsRepository(string connectionString)
{
    /// <summary>A personal system changes its settings a handful of times a
    /// year; the bound only keeps a runaway client from making the list heavy.</summary>
    private const int MaxVersions = 200;

    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    public async Task<IReadOnlyList<AccountSettingsRow>> ListAsync(CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        var rows = await conn.QueryAsync<AccountSettingsRow>(
            """
            SELECT s.version_id AS VersionId, s.firm AS Firm, s.settings::text AS SettingsJson,
                   s.requested_at AS RequestedAt, s.deferred AS Deferred,
                   s.deferral_reasons::text AS DeferralReasonsJson, s.cancelled_at AS CancelledAt,
                   EXISTS (SELECT 1 FROM trading_day_anchors a
                           WHERE a.starts_at_utc > s.requested_at) AS DayStartedSince
            FROM account_settings s
            ORDER BY s.requested_at DESC
            LIMIT @limit
            """,
            new { limit = MaxVersions });
        return rows.AsList();
    }

    /// <summary>
    /// Every account whose trading day is in progress, with its trades since
    /// the anchor, plus every account locked right now.
    ///
    /// "In progress" = its latest anchor started less than 25 hours ago. The
    /// Gateway only resolves an anchor while the observer is attached, so an
    /// account last seen three days ago still has a three-day-old "latest"
    /// anchor — counting its trades would defer every change forever. 25 and
    /// not 24: a DST night makes a 25-hour trading day, and when in doubt
    /// this rule should count one hour too many, never one too few.
    /// </summary>
    public async Task<IReadOnlyList<SessionFact>> GetSessionFactsAsync(CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        var rows = await conn.QueryAsync<SessionFact>(
            """
            WITH latest AS (
                SELECT DISTINCT ON (account_id) account_id, starts_at_utc
                FROM trading_day_anchors
                ORDER BY account_id, starts_at_utc DESC
            ),
            in_progress AS (
                SELECT l.account_id, l.starts_at_utc,
                       (SELECT count(*) FROM position_opens p
                        WHERE p.account_id = l.account_id
                          AND p.opened_at >= l.starts_at_utc)::int AS trades_today
                FROM latest l
                WHERE l.starts_at_utc > now() - interval '25 hours'
            ),
            locked AS (
                SELECT DISTINCT ON (account_id) account_id, reason
                FROM risk_lockouts
                WHERE cleared_at IS NULL AND (until IS NULL OR until > now())
                ORDER BY account_id, since DESC
            )
            SELECT coalesce(i.account_id, k.account_id) AS AccountId,
                   i.starts_at_utc AS DayAnchorStartsAtUtc,
                   coalesce(i.trades_today, 0) AS TradesToday,
                   k.reason AS ActiveLockoutReason
            FROM in_progress i
            FULL OUTER JOIN locked k ON k.account_id = i.account_id
            ORDER BY 1
            """);
        return rows.AsList();
    }

    public async Task<AccountSettingsRow> InsertAsync(
        string firm, string settingsJson, GuardDecision decision, CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        // A row just written cannot have an anchor after it: anchors are day
        // starts, never in the future — hence the literal false.
        return await conn.QuerySingleAsync<AccountSettingsRow>(
            """
            INSERT INTO account_settings
                (version_id, firm, settings, requested_at, deferred, deferral_reasons)
            VALUES (@versionId, @firm, @settingsJson::jsonb, now(), @deferred, @reasonsJson::jsonb)
            RETURNING version_id AS VersionId, firm AS Firm, settings::text AS SettingsJson,
                      requested_at AS RequestedAt, deferred AS Deferred,
                      deferral_reasons::text AS DeferralReasonsJson, cancelled_at AS CancelledAt,
                      false AS DayStartedSince
            """,
            new
            {
                versionId = Guid.NewGuid().ToString(),
                firm,
                settingsJson,
                deferred = decision.Deferred,
                reasonsJson = JsonSerializer.Serialize(decision.Reasons, Json),
            });
    }

    /// <summary>
    /// Withdraw a deferred change before it has governed any session. Once a
    /// trading day has started after the request — on any account — the
    /// change may already be the rule somewhere, and undoing it is a change
    /// like any other: it goes through the guard as a new version.
    /// </summary>
    public async Task<CancelOutcome> TryCancelAsync(string versionId, CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        var row = await conn.QuerySingleOrDefaultAsync<(bool Deferred, DateTime? CancelledAt, bool DayStartedSince)?>(
            """
            SELECT s.deferred AS Deferred, s.cancelled_at AS CancelledAt,
                   EXISTS (SELECT 1 FROM trading_day_anchors a
                           WHERE a.starts_at_utc > s.requested_at) AS DayStartedSince
            FROM account_settings s
            WHERE s.version_id = @versionId
            """,
            new { versionId });

        if (row is null)
        {
            return CancelOutcome.NotFound;
        }
        if (!row.Value.Deferred)
        {
            return CancelOutcome.NotDeferred;
        }
        if (row.Value.CancelledAt is not null)
        {
            return CancelOutcome.AlreadyCancelled;
        }
        if (row.Value.DayStartedSince)
        {
            return CancelOutcome.AlreadyInEffect;
        }

        // Same conditions again in the UPDATE itself: an anchor resolved
        // between the read above and this write must still win.
        var updated = await conn.ExecuteAsync(
            """
            UPDATE account_settings SET cancelled_at = now()
            WHERE version_id = @versionId AND deferred AND cancelled_at IS NULL
              AND NOT EXISTS (SELECT 1 FROM trading_day_anchors a
                              WHERE a.starts_at_utc > account_settings.requested_at)
            """,
            new { versionId });
        return updated == 1 ? CancelOutcome.Cancelled : CancelOutcome.AlreadyInEffect;
    }

    public async Task<AccountSettingsRow?> GetAsync(string versionId, CancellationToken ct)
    {
        await using var conn = new NpgsqlConnection(connectionString);
        await conn.OpenAsync(ct);
        return await conn.QuerySingleOrDefaultAsync<AccountSettingsRow>(
            """
            SELECT s.version_id AS VersionId, s.firm AS Firm, s.settings::text AS SettingsJson,
                   s.requested_at AS RequestedAt, s.deferred AS Deferred,
                   s.deferral_reasons::text AS DeferralReasonsJson, s.cancelled_at AS CancelledAt,
                   EXISTS (SELECT 1 FROM trading_day_anchors a
                           WHERE a.starts_at_utc > s.requested_at) AS DayStartedSince
            FROM account_settings s
            WHERE s.version_id = @versionId
            """,
            new { versionId });
    }
}
