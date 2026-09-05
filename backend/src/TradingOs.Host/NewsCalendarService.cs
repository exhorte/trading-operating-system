using Microsoft.AspNetCore.SignalR;
using TradingOs.Contracts;
using TradingOs.Gateway;
using TradingOs.Persistence;

namespace TradingOs.Host;

/// <summary>
/// T03 — polls FRED for the whitelisted release calendar, caches it in
/// Postgres (NewsCalendarRepository), and broadcasts the current upcoming
/// list to every dashboard. Independent of GatewayBridgeService: this has
/// nothing to do with the MT5 gateway, it is a separate external data source
/// (context/adr/0003-stack-et-topologie.md: HTTP is a secondary surface).
///
/// Fail-closed by construction: on boot this broadcasts whatever the DB
/// cache currently holds (survives a restart) BEFORE any network attempt,
/// and a release_id whose refresh fails keeps its last-known-good cache
/// rather than being wiped — see NewsCalendarRepository.ReplaceUpcomingAsync
/// (per-release, transactional) and GetUpcomingOrNullAsync (null only when
/// truly never synced).
/// </summary>
public sealed class NewsCalendarService(
    IHttpClientFactory httpClientFactory,
    NewsCalendarRepository repository,
    IHubContext<CockpitHub> hub,
    IConfiguration configuration,
    ILogger<NewsCalendarService> logger) : BackgroundService
{
    private const string Source = "news-calendar";

    /// <summary>Release schedules are announced months ahead and almost never
    /// change — no need to poll more often than this.</summary>
    private static readonly TimeSpan RefreshInterval = TimeSpan.FromHours(6);

    /// <summary>Only the nearest few matter to the gate or the cockpit chip.</summary>
    private const int KeepPerRelease = 3;

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        // Warm broadcast from whatever the DB already has, before the first
        // network attempt — a dashboard that connects during a FRED outage
        // still sees the last-known-good calendar, not a blank slate.
        await BroadcastCurrentCacheAsync(ct);

        while (!ct.IsCancellationRequested)
        {
            await RefreshAsync(ct);
            await BroadcastCurrentCacheAsync(ct);
            try
            {
                await Task.Delay(RefreshInterval, ct);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }
    }

    private async Task RefreshAsync(CancellationToken ct)
    {
        var apiKey = configuration["Fred:ApiKey"];
        if (string.IsNullOrWhiteSpace(apiKey))
        {
            logger.LogWarning(
                "Fred:ApiKey is not configured — news calendar cache will not refresh " +
                "(set the FRED__ApiKey environment variable or dotnet user-secrets; never commit it)");
            return;
        }

        var client = new FredCalendarClient(httpClientFactory.CreateClient("fred"), apiKey);
        var nowUtc = DateTime.UtcNow;

        foreach (var spec in FredReleaseSchedule.Whitelist)
        {
            try
            {
                var instants = await client.FetchUpcomingUtcInstantsAsync(spec, nowUtc, ct);
                await repository.ReplaceUpcomingAsync(
                    spec.ReleaseId, spec.Label, instants.Take(KeepPerRelease).ToList(), nowUtc, ct);
            }
            catch (OperationCanceledException)
            {
                return;
            }
            catch (Exception ex)
            {
                // One release failing (bad key, FRED outage, rate limit) must
                // never wipe its existing cache nor block the other releases.
                logger.LogWarning(ex, "FRED refresh failed for release {ReleaseId} ({Label})", spec.ReleaseId, spec.Label);
            }
        }
    }

    private async Task BroadcastCurrentCacheAsync(CancellationToken ct)
    {
        IReadOnlyList<NewsReleaseRow>? rows;
        try
        {
            rows = await repository.GetUpcomingOrNullAsync(DateTime.UtcNow, ct);
        }
        catch (OperationCanceledException)
        {
            return;
        }
        catch (Exception ex)
        {
            logger.LogWarning(ex, "Could not read news calendar cache");
            return;
        }

        var releases = rows?.Select(r => new UpcomingRelease(r.ReleaseId, r.Label, r.ScheduledAt.ToString("o"))).ToArray();
        var envelope = Envelope<object>.Create(EventTypes.MarketCalendarUpdated, Source, new CalendarUpdatedPayload(releases));
        await hub.Clients.All.SendAsync("event", envelope, ct);
    }
}
