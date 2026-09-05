namespace TradingOs.Gateway;

/// <summary>
/// T03 — the FRED whitelist (context/product/tools/T03-gate-news.md). This
/// list IS the impact classification; do not add a source or an "impact"
/// field elsewhere. Verified via fred.stlouisfed.org/release?rid={id} on
/// 2026-09-05: 10 (CPI), 50 (Employment Situation/NFP), 54 (Personal Income
/// and Outlays/PCE), 9 (Advance Monthly Sales for Retail and Food Services),
/// 101 (FOMC Press Release). ISM is deliberately absent: the Institute for
/// Supply Management had all its series pulled from FRED in 2016 over
/// licensing — no FRED release_id exists for it, and the card explicitly
/// rules out commercial sources and ForexFactory as substitutes.
///
/// FRED's fred/release/dates endpoint returns only a calendar DATE, never a
/// time-of-day. HourEt/MinuteEt below are each release's long-standing,
/// publicly documented release time (BLS/BEA/Census: 8:30am ET; FOMC
/// statement: 2:00pm ET since March 2013) — stable schedule conventions, not
/// data FRED provides. Combined with the fetched date via
/// <see cref="ToUtcInstant"/>, which resolves the real US Eastern
/// EST/EDT offset for that specific date (never a hardcoded UTC offset).
/// </summary>
public sealed record FredReleaseSpec(int ReleaseId, string Label, int HourEt, int MinuteEt);

public static class FredReleaseSchedule
{
    public static readonly FredReleaseSpec[] Whitelist =
    [
        new(10, "CPI US", 8, 30),
        new(50, "NFP US", 8, 30),
        new(54, "PCE US", 8, 30),
        new(9, "Retail Sales US", 8, 30),
        new(101, "FOMC", 14, 0),
    ];

    private static readonly TimeZoneInfo Eastern = ResolveEastern();

    private static TimeZoneInfo ResolveEastern()
    {
        try
        {
            return TimeZoneInfo.FindSystemTimeZoneById("America/New_York"); // IANA (Linux/macOS, modern Windows)
        }
        catch (TimeZoneNotFoundException)
        {
            return TimeZoneInfo.FindSystemTimeZoneById("Eastern Standard Time"); // Windows ID fallback
        }
    }

    /// <summary>Resolves the real EST/EDT offset for `releaseDate` — never a
    /// hardcoded UTC offset, so a release near a DST transition is correct.</summary>
    public static DateTime ToUtcInstant(DateOnly releaseDate, int hourEt, int minuteEt)
    {
        var localUnspecified = new DateTime(
            releaseDate.Year, releaseDate.Month, releaseDate.Day, hourEt, minuteEt, 0, DateTimeKind.Unspecified);
        return TimeZoneInfo.ConvertTimeToUtc(localUnspecified, Eastern);
    }
}
