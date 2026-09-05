using TradingOs.Gateway;

namespace TradingOs.Gateway.Tests;

public class TradingDayAnchorTests
{
    [Fact]
    public void Resolves_server_midnight_for_a_positive_offset()
    {
        // UTC+3: 2026-09-05T10:00Z is 13:00 server-local -> midnight was 2026-09-04T21:00Z.
        var utcNow = new DateTimeOffset(2026, 9, 5, 10, 0, 0, TimeSpan.Zero);
        var anchor = TradingDayAnchor.ResolveTodayStartUtc(utcNow, serverUtcOffsetMinutes: 180);
        Assert.Equal(new DateTimeOffset(2026, 9, 4, 21, 0, 0, TimeSpan.Zero), anchor);
    }

    [Fact]
    public void Resolves_server_midnight_for_a_negative_offset()
    {
        // UTC-5: 2026-09-05T10:00Z is 05:00 server-local -> midnight is 2026-09-05T05:00Z.
        var utcNow = new DateTimeOffset(2026, 9, 5, 10, 0, 0, TimeSpan.Zero);
        var anchor = TradingDayAnchor.ResolveTodayStartUtc(utcNow, serverUtcOffsetMinutes: -300);
        Assert.Equal(new DateTimeOffset(2026, 9, 5, 5, 0, 0, TimeSpan.Zero), anchor);
    }

    [Fact]
    public void Rolls_over_exactly_at_the_server_midnight_instant()
    {
        // Same +180 offset as the FX/gold swap rollover this project already
        // documents at 21:00 UTC — one minute before/after must land on
        // different trading days.
        var justBefore = new DateTimeOffset(2026, 9, 4, 20, 59, 0, TimeSpan.Zero);
        var justAfter = new DateTimeOffset(2026, 9, 4, 21, 1, 0, TimeSpan.Zero);

        Assert.Equal(
            new DateTimeOffset(2026, 9, 3, 21, 0, 0, TimeSpan.Zero),
            TradingDayAnchor.ResolveTodayStartUtc(justBefore, serverUtcOffsetMinutes: 180));
        Assert.Equal(
            new DateTimeOffset(2026, 9, 4, 21, 0, 0, TimeSpan.Zero),
            TradingDayAnchor.ResolveTodayStartUtc(justAfter, serverUtcOffsetMinutes: 180));
    }

    [Fact]
    public void Zero_offset_is_plain_utc_midnight()
    {
        var utcNow = new DateTimeOffset(2026, 9, 5, 10, 0, 0, TimeSpan.Zero);
        var anchor = TradingDayAnchor.ResolveTodayStartUtc(utcNow, serverUtcOffsetMinutes: 0);
        Assert.Equal(new DateTimeOffset(2026, 9, 5, 0, 0, 0, TimeSpan.Zero), anchor);
    }
}
