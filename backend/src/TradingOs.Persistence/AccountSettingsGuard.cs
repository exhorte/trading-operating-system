namespace TradingOs.Persistence;

/// <summary>
/// One account whose trading day is in progress (latest anchor less than 25 h
/// old) or that is locked right now — see AccountSettingsRepository.GetSessionFactsAsync.
/// </summary>
public sealed record SessionFact(
    string AccountId,
    DateTime? DayAnchorStartsAtUtc,
    int TradesToday,
    string? ActiveLockoutReason);

/// <summary>What the backend sees of the MT5 terminal at this instant: the
/// read-only observer's link (GatewayState), never the page's belief.</summary>
public sealed record LiveLink(bool ObserverConnected, string? AccountId, int OpenPositions);

/// <summary>Structured on purpose — the cockpit words it
/// (lib/accounts/settings.ts::describeGuardReason), the ledger stores it.</summary>
public sealed record GuardReason(string Code, string? AccountId, int? Count, string? Detail);

public sealed record GuardDecision(bool Deferred, IReadOnlyList<GuardReason> Reasons);

/// <summary>
/// T12 incrément 2 — when does a settings change requested from the cockpit
/// take effect?
///
/// Immediately only when no session is in progress: no trade opened since the
/// day anchor on any account, no active lockout on any account, a live
/// account to look at, and no position open on it. Otherwise it waits for the
/// first trading-day anchor that starts after the request. The FTMO size and
/// the Exness reference are the denominators of both loss gates
/// (lib/risk/evaluate.ts): raising one mid-session loosens the daily limit in
/// dollars — the exact move this product exists to prevent, and the reason
/// the rule lives here, where the change is persisted, rather than as a
/// disabled button (ADR 0007).
///
/// "No live account" defers too: without the observer nothing can confirm
/// that no position is open. Every account is checked, not only the one
/// connected — otherwise switching accounts in MT5 would be enough to slip a
/// change past the rule.
///
/// Pure, so it is tested without a database (AccountSettingsGuardTests).
/// </summary>
public static class AccountSettingsGuard
{
    public const string NoLiveAccount = "no_live_account";
    public const string OpenPositions = "open_positions";
    public const string TradesToday = "trades_today";
    public const string ActiveLockout = "active_lockout";

    public static GuardDecision Decide(LiveLink link, IReadOnlyList<SessionFact> sessions)
    {
        var reasons = new List<GuardReason>();

        if (!link.ObserverConnected || link.AccountId is null)
        {
            reasons.Add(new GuardReason(NoLiveAccount, null, null, null));
        }
        else if (link.OpenPositions > 0)
        {
            reasons.Add(new GuardReason(OpenPositions, link.AccountId, link.OpenPositions, null));
        }

        foreach (var session in sessions.OrderBy(s => s.AccountId, StringComparer.Ordinal))
        {
            if (session.TradesToday > 0)
            {
                reasons.Add(new GuardReason(TradesToday, session.AccountId, session.TradesToday, null));
            }
            if (session.ActiveLockoutReason is { } lockoutReason)
            {
                reasons.Add(new GuardReason(ActiveLockout, session.AccountId, null, lockoutReason));
            }
        }

        return new GuardDecision(reasons.Count > 0, reasons);
    }
}
