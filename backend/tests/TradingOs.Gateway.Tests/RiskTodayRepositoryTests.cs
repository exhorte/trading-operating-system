using TradingOs.Persistence;

namespace TradingOs.Gateway.Tests;

/// <summary>
/// T02b: pure consecutive-loss counting, no database needed — mirrors the
/// "isolate the pure decision, DB integration untested here" pattern used
/// elsewhere in this repo (e.g. TradingDayAnchorTests).
/// </summary>
public class RiskTodayRepositoryTests
{
    private static ClosedTradeStreakRow Trade(double pnl, string closedAtIso) =>
        new(pnl, DateTime.Parse(closedAtIso).ToUniversalTime());

    [Fact]
    public void Counts_the_trailing_run_of_losses_from_most_recent_first()
    {
        var mostRecentFirst = new[]
        {
            Trade(-5, "2026-09-05T10:20:00Z"),
            Trade(-3, "2026-09-05T10:10:00Z"),
            Trade(12, "2026-09-05T10:00:00Z"), // win — the streak stops here
            Trade(-1, "2026-09-05T09:00:00Z"),
        };

        var (count, lastLossAt) = RiskTodayRepository.CountConsecutiveLosses(mostRecentFirst);

        Assert.Equal(2, count);
        Assert.Equal(DateTime.Parse("2026-09-05T10:20:00Z").ToUniversalTime(), lastLossAt);
    }

    [Fact]
    public void Zero_when_the_most_recent_trade_was_a_win()
    {
        var (count, lastLossAt) = RiskTodayRepository.CountConsecutiveLosses(
            [Trade(1, "2026-09-05T10:00:00Z"), Trade(-1, "2026-09-05T09:00:00Z")]);

        Assert.Equal(0, count);
        Assert.Null(lastLossAt);
    }

    [Fact]
    public void Zero_when_there_is_no_trade_history()
    {
        var (count, lastLossAt) = RiskTodayRepository.CountConsecutiveLosses([]);

        Assert.Equal(0, count);
        Assert.Null(lastLossAt);
    }

    [Fact]
    public void Does_not_reset_across_a_streak_that_spans_the_day_anchor()
    {
        // T02-lockout.md: unlike tradesToday, the streak has no calendar
        // boundary — two losses late one day plus one at the next day's
        // open are still three consecutive losses.
        var mostRecentFirst = new[]
        {
            Trade(-1, "2026-09-05T07:00:00Z"), // after the next day's anchor
            Trade(-2, "2026-09-04T23:50:00Z"),
            Trade(-3, "2026-09-04T23:40:00Z"),
        };

        var (count, _) = RiskTodayRepository.CountConsecutiveLosses(mostRecentFirst);

        Assert.Equal(3, count);
    }
}
