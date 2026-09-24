using System.Text.Json;
using Microsoft.AspNetCore.SignalR;
using TradingOs.Contracts;
using TradingOs.Gateway;
using TradingOs.Persistence;

namespace TradingOs.Host;

/// <summary>
/// T12 incrément 2 — the HTTP surface of the cockpit's Settings screen.
/// HTTP because this is administration, not trading flow (ADR 0003).
///
/// The anti-tilt rule (AccountSettingsGuard) is decided here, at the moment
/// the ledger is written, from the backend's own facts: the observer's link
/// and the database. The page only displays the decision it is given — it
/// never computes one (ADR 0007: an engine-side rule, not an interface
/// condition). What the page does own is the resolution of which version is
/// in effect, because that depends on the trading-day anchor it already
/// tracks for the risk engine (lib/accounts/settings.ts).
///
/// Nothing here connects to a broker or accepts a credential: the settings
/// describe an account, the MT5 terminal logs into it (ADR 0003).
/// </summary>
public static class AccountSettingsEndpoints
{
    private const string Source = "account-settings";

    public static void MapAccountSettingsEndpoints(this WebApplication app)
    {
        app.MapGet("/api/account-settings", async (
            AccountSettingsRepository repository,
            GatewayState state,
            Mt5AgentServer agentServer,
            ILoggerFactory loggers,
            CancellationToken ct) =>
        {
            try
            {
                var versions = await repository.ListAsync(ct);
                var sessions = await repository.GetSessionFactsAsync(ct);
                return Results.Ok(new
                {
                    versions = versions.Select(ToDto),
                    guard = AccountSettingsGuard.Decide(LiveLinkOf(state, agentServer), sessions),
                    evaluatedAt = DateTime.UtcNow.ToString("o"),
                });
            }
            catch (Exception ex)
            {
                loggers.CreateLogger(Source).LogError(ex, "GET /api/account-settings failed");
                return Results.Problem(detail: $"{ex.GetType().Name}: {ex.Message}", statusCode: 503);
            }
        });

        app.MapPost("/api/account-settings", async (
            AccountSettingsRequest request,
            AccountSettingsRepository repository,
            GatewayState state,
            Mt5AgentServer agentServer,
            PersistenceWriter writer,
            IHubContext<CockpitHub> hub,
            ILoggerFactory loggers,
            CancellationToken ct) =>
        {
            var (normalized, error) = AccountSettingsValidation.Validate(request.Firm, request.Settings);
            if (error is not null)
            {
                return Results.BadRequest(new { error = "invalid_settings", message = error });
            }
            try
            {
                // Facts read now, at the moment of writing — never the ones the
                // page displayed when it was opened.
                var sessions = await repository.GetSessionFactsAsync(ct);
                var decision = AccountSettingsGuard.Decide(LiveLinkOf(state, agentServer), sessions);
                var row = await repository.InsertAsync(request.Firm!, normalized!, decision, ct);
                await AnnounceAsync(hub, writer, row, "requested");
                return Results.Ok(new { version = ToDto(row), guard = decision });
            }
            catch (Exception ex)
            {
                loggers.CreateLogger(Source).LogError(ex, "POST /api/account-settings failed");
                return Results.Problem(detail: $"{ex.GetType().Name}: {ex.Message}", statusCode: 503);
            }
        });

        app.MapPost("/api/account-settings/{versionId}/cancel", async (
            string versionId,
            AccountSettingsRepository repository,
            PersistenceWriter writer,
            IHubContext<CockpitHub> hub,
            ILoggerFactory loggers,
            CancellationToken ct) =>
        {
            try
            {
                var outcome = await repository.TryCancelAsync(versionId, ct);
                if (outcome == CancelOutcome.NotFound)
                {
                    return Results.NotFound(new { error = "not_found", message = "Version inconnue." });
                }
                if (outcome != CancelOutcome.Cancelled)
                {
                    return Results.Conflict(new { error = CodeOf(outcome), message = Describe(outcome) });
                }
                var row = await repository.GetAsync(versionId, ct);
                if (row is not null)
                {
                    await AnnounceAsync(hub, writer, row, "cancelled");
                }
                return Results.Ok(new { version = row is null ? null : ToDto(row) });
            }
            catch (Exception ex)
            {
                loggers.CreateLogger(Source).LogError(ex, "POST /api/account-settings/{VersionId}/cancel failed", versionId);
                return Results.Problem(detail: $"{ex.GetType().Name}: {ex.Message}", statusCode: 503);
            }
        });
    }

    /// <summary>
    /// The read-only observer's link — the only thing that knows whether an
    /// account is live right now and what it holds. Its account and positions
    /// outlive a disconnection in GatewayState, so they only count while the
    /// observer's own state says "connected".
    /// </summary>
    private static LiveLink LiveLinkOf(GatewayState state, Mt5AgentServer agentServer)
    {
        var snapshot = state.Snapshot(agentServer.IsConnected);
        var observerConnected = snapshot.Agents.Any(agent => agent.State == "connected");
        return new LiveLink(observerConnected, snapshot.Account?.AccountId, snapshot.Positions.Length);
    }

    private static async Task AnnounceAsync(
        IHubContext<CockpitHub> hub, PersistenceWriter writer, AccountSettingsRow row, string action)
    {
        var payload = new AccountSettingsChangedPayload(
            row.VersionId,
            row.Firm,
            action,
            row.Deferred,
            ParseJson(row.SettingsJson),
            ParseJson(row.DeferralReasonsJson));
        var envelope = Envelope<object>.Create(EventTypes.AccountsSettingsChanged, Source, payload, row.VersionId);
        GatewayBridgeService.Persist(writer, envelope);
        await hub.Clients.All.SendAsync("event", envelope);
    }

    private static AccountSettingsVersionDto ToDto(AccountSettingsRow row) => new(
        row.VersionId,
        row.Firm,
        ParseJson(row.SettingsJson),
        Iso(row.RequestedAt),
        row.Deferred,
        ParseJson(row.DeferralReasonsJson),
        row.CancelledAt is { } cancelledAt ? Iso(cancelledAt) : null,
        row.DayStartedSince);

    private static JsonElement ParseJson(string json)
    {
        using var document = JsonDocument.Parse(json);
        return document.RootElement.Clone();
    }

    private static string Iso(DateTime utc) => DateTime.SpecifyKind(utc, DateTimeKind.Utc).ToString("o");

    private static string CodeOf(CancelOutcome outcome) => outcome switch
    {
        CancelOutcome.NotDeferred => "not_deferred",
        CancelOutcome.AlreadyCancelled => "already_cancelled",
        CancelOutcome.AlreadyInEffect => "already_in_effect",
        _ => "unknown",
    };

    private static string Describe(CancelOutcome outcome) => outcome switch
    {
        CancelOutcome.NotDeferred =>
            "Ce changement s'est appliqué tout de suite : il n'y a rien à annuler. Pour revenir en " +
            "arrière, enregistre une nouvelle version.",
        CancelOutcome.AlreadyCancelled => "Ce changement est déjà annulé.",
        CancelOutcome.AlreadyInEffect =>
            "Une journée de trading a commencé depuis ce changement : il a pu gouverner une séance. " +
            "Pour revenir en arrière, enregistre une nouvelle version — elle passe par le même verrou.",
        _ => "Annulation impossible.",
    };
}
