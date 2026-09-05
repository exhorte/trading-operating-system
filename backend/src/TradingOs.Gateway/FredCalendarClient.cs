using System.Text.Json;
using System.Text.Json.Serialization;

namespace TradingOs.Gateway;

/// <summary>
/// T03 — thin client for the FRED "fred/release/dates" endpoint
/// (https://fred.stlouisfed.org/docs/api/fred/release_dates.html). Fetches
/// one whitelisted release, filters to future dates, and resolves each to a
/// UTC instant via FredReleaseSchedule. Read-only, like the MT5 observer;
/// this never decides anything, it only reports FRED's own schedule.
/// </summary>
public sealed class FredCalendarClient(HttpClient http, string apiKey)
{
    private const string BaseUrl = "https://api.stlouisfed.org/fred/release/dates";

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    private sealed record FredReleaseDate(int ReleaseId, string Date);

    private sealed record FredReleaseDatesResponse([property: JsonPropertyName("release_dates")] FredReleaseDate[] ReleaseDates);

    /// <summary>Every future UTC instant FRED has scheduled for this release,
    /// soonest first. Throws on a network/auth failure — the caller decides
    /// how to treat that (T03: never wipe the existing cache on a failure).</summary>
    public async Task<IReadOnlyList<DateTime>> FetchUpcomingUtcInstantsAsync(
        FredReleaseSpec spec,
        DateTime nowUtc,
        CancellationToken ct)
    {
        var url = $"{BaseUrl}?release_id={spec.ReleaseId}&include_release_dates_with_no_data=true" +
                  $"&sort_order=asc&file_type=json&api_key={Uri.EscapeDataString(apiKey)}";
        using var response = await http.GetAsync(url, ct);
        response.EnsureSuccessStatusCode();
        var body = await response.Content.ReadAsStringAsync(ct);
        var parsed = JsonSerializer.Deserialize<FredReleaseDatesResponse>(body, JsonOptions)
            ?? throw new InvalidOperationException("FRED release/dates response could not be parsed");

        return parsed.ReleaseDates
            .Select(d => FredReleaseSchedule.ToUtcInstant(DateOnly.ParseExact(d.Date, "yyyy-MM-dd"), spec.HourEt, spec.MinuteEt))
            .Where(instant => instant >= nowUtc)
            .OrderBy(instant => instant)
            .ToList();
    }
}
