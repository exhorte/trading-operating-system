using TradingOs.Persistence;

namespace TradingOs.Gateway.Tests;

/// <summary>
/// T12 incrément 2 — the anti-tilt rule on account settings: immediate only
/// when no session is in progress anywhere, deferred to the next trading day
/// otherwise. Pure, like RiskTodayRepositoryTests.
/// </summary>
public class AccountSettingsGuardTests
{
    private static readonly LiveLink QuietLiveAccount = new(ObserverConnected: true, AccountId: "477029930", OpenPositions: 0);

    private static SessionFact Session(string accountId, int tradesToday = 0, string? lockout = null) =>
        new(accountId, DateTime.Parse("2026-09-23T00:00:00Z").ToUniversalTime(), tradesToday, lockout);

    [Fact]
    public void Applies_at_once_when_the_live_account_is_flat_and_nothing_has_happened_today()
    {
        var decision = AccountSettingsGuard.Decide(QuietLiveAccount, [Session("477029930")]);

        Assert.False(decision.Deferred);
        Assert.Empty(decision.Reasons);
    }

    [Fact]
    public void Defers_after_a_trade_since_the_day_anchor()
    {
        var decision = AccountSettingsGuard.Decide(QuietLiveAccount, [Session("477029930", tradesToday: 2)]);

        Assert.True(decision.Deferred);
        var reason = Assert.Single(decision.Reasons);
        Assert.Equal(AccountSettingsGuard.TradesToday, reason.Code);
        Assert.Equal("477029930", reason.AccountId);
        Assert.Equal(2, reason.Count);
    }

    [Fact]
    public void Defers_while_a_position_is_open()
    {
        var decision = AccountSettingsGuard.Decide(QuietLiveAccount with { OpenPositions = 1 }, []);

        Assert.True(decision.Deferred);
        var reason = Assert.Single(decision.Reasons);
        Assert.Equal(AccountSettingsGuard.OpenPositions, reason.Code);
        Assert.Equal(1, reason.Count);
    }

    [Fact]
    public void Defers_while_a_lockout_is_active()
    {
        var decision = AccountSettingsGuard.Decide(
            QuietLiveAccount, [Session("477029930", lockout: "Daily loss guard")]);

        Assert.True(decision.Deferred);
        var reason = Assert.Single(decision.Reasons);
        Assert.Equal(AccountSettingsGuard.ActiveLockout, reason.Code);
        Assert.Equal("Daily loss guard", reason.Detail);
    }

    [Fact]
    public void Defers_when_no_account_is_live_since_open_positions_cannot_be_ruled_out()
    {
        var decision = AccountSettingsGuard.Decide(new LiveLink(false, "477029930", 0), []);

        Assert.True(decision.Deferred);
        Assert.Equal(AccountSettingsGuard.NoLiveAccount, Assert.Single(decision.Reasons).Code);
    }

    [Fact]
    public void Defers_when_the_observer_is_up_but_has_not_reported_an_account_yet()
    {
        var decision = AccountSettingsGuard.Decide(new LiveLink(true, null, 0), []);

        Assert.True(decision.Deferred);
        Assert.Equal(AccountSettingsGuard.NoLiveAccount, Assert.Single(decision.Reasons).Code);
    }

    // The loophole this closes: trade account A, switch MT5 to a quiet
    // account B, loosen A's settings, switch back — same day.
    [Fact]
    public void Looks_at_every_account_not_only_the_one_connected()
    {
        var decision = AccountSettingsGuard.Decide(
            QuietLiveAccount,
            [Session("477029930"), Session("511333949", tradesToday: 3)]);

        Assert.True(decision.Deferred);
        var reason = Assert.Single(decision.Reasons);
        Assert.Equal("511333949", reason.AccountId);
    }

    [Fact]
    public void Lists_every_reason_in_a_stable_order()
    {
        var decision = AccountSettingsGuard.Decide(
            QuietLiveAccount with { OpenPositions = 2 },
            [Session("b", lockout: "Kill switch"), Session("a", tradesToday: 1)]);

        Assert.Equal(
            new[] { AccountSettingsGuard.OpenPositions, AccountSettingsGuard.TradesToday, AccountSettingsGuard.ActiveLockout },
            decision.Reasons.Select(r => r.Code));
        Assert.Equal(new[] { "477029930", "a", "b" }, decision.Reasons.Select(r => r.AccountId));
    }
}
