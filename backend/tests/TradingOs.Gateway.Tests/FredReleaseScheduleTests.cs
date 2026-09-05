using TradingOs.Gateway;

namespace TradingOs.Gateway.Tests;

/// <summary>
/// T03: FRED gives only a calendar date, never a time — this is the pure
/// logic that combines it with each release's known ET release time and
/// resolves the correct UTC instant, DST included. Real-world source: "For
/// release at 2:00 p.m. EST December 10, 2025" (federalreserve.gov FOMC
/// statement) confirms the EST case; the EDT case follows the same rule for
/// a summer date.
/// </summary>
public class FredReleaseScheduleTests
{
    [Fact]
    public void Resolves_EST_correctly_in_winter_verified_against_a_real_FOMC_release()
    {
        var utc = FredReleaseSchedule.ToUtcInstant(new DateOnly(2025, 12, 10), 14, 0);
        Assert.Equal(new DateTime(2025, 12, 10, 19, 0, 0, DateTimeKind.Utc), utc); // EST = UTC-5
    }

    [Fact]
    public void Resolves_EDT_correctly_in_summer()
    {
        var utc = FredReleaseSchedule.ToUtcInstant(new DateOnly(2026, 7, 14), 8, 30);
        Assert.Equal(new DateTime(2026, 7, 14, 12, 30, 0, DateTimeKind.Utc), utc); // EDT = UTC-4
    }

    [Fact]
    public void Whitelist_has_no_ISM_and_matches_the_verified_release_ids()
    {
        var ids = FredReleaseSchedule.Whitelist.Select(r => r.ReleaseId).OrderBy(id => id).ToArray();
        Assert.Equal([9, 10, 50, 54, 101], ids);
    }
}
