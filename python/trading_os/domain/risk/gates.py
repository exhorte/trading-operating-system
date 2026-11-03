"""Safety gates. Each is a pure function returning a ``GateResult``. A gate whose input is unknown reports ``open``
with an honest ``n/a`` detail — never a fabricated pass — **except** where missing data must block: the news gate
(unknown or stale calendar) and every gate that needs a live tick when an actual order is being reviewed.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from trading_os.domain.market.calendar import UpcomingRelease, is_news_blackout, next_release
from trading_os.domain.risk.policy import DrawdownPolicy, NewsPolicy, PositionLimits, RiskProfile
from trading_os.domain.risk.state import GateResult, round_half_up


def _pct(value: float) -> str:
    rounded = round_half_up(value, 1)
    return f"{rounded:g}%"


def _gate(gate_id: str, label: str, blocked: bool, detail: str) -> GateResult:
    return GateResult(gate_id=gate_id, label=label, state="blocked" if blocked else "open", detail=detail)


def daily_loss_gate(used_percent: float, policy: DrawdownPolicy) -> GateResult:
    return _gate(
        "gate-daily-loss",
        "Daily loss guard",
        used_percent >= policy.daily_loss_limit_percent,
        f"{_pct(used_percent)} used of {_pct(policy.daily_loss_limit_percent)}",
    )


def weekly_loss_gate(used_percent: float, policy: DrawdownPolicy) -> GateResult:
    return _gate(
        "gate-weekly-loss",
        "Weekly loss guard",
        used_percent >= policy.weekly_loss_limit_percent,
        f"{_pct(used_percent)} used of {_pct(policy.weekly_loss_limit_percent)}",
    )


def performance_stop_gate(performance_percent: float | None, stop_level_percent: int) -> GateResult:
    """The grid's last row: at ``stop_level_percent`` of the initial capital (−5 %) no new entry. Evaluated every
    day against the same initial capital, so a new day never lifts it. Without an initial capital there is no
    performance to read: the gate says so, and the allowance (not this gate) refuses the entry."""
    if performance_percent is None:
        return _gate("gate-performance-stop", "Performance stop", False, "n/a (initial capital not fixed)")
    return _gate(
        "gate-performance-stop",
        "Performance stop",
        round(performance_percent, 6) <= stop_level_percent,
        f"{performance_percent:+.2f}% vs initial capital (stop at {stop_level_percent:+d}%)",
    )


def max_drawdown_gate(used_percent: float, policy: DrawdownPolicy) -> GateResult:
    return _gate(
        "gate-total-dd",
        "Max drawdown guard",
        used_percent >= policy.max_drawdown_limit_percent,
        f"{_pct(used_percent)} used of {_pct(policy.max_drawdown_limit_percent)}",
    )


def open_risk_gate(
    open_risk_percent: float, limit_percent: float, *, unprotected: Sequence[str] = (), unknown_spec: Sequence[str] = ()
) -> GateResult:
    """Blocks when the open risk exceeds the limit — and when it cannot be bounded: a position without a stop has
    unbounded risk (« no trade without a stop »), a position on a symbol we have no specification for is unmeasured."""
    if unprotected:
        return _gate("gate-open-risk", "Open risk guard", True, f"position without a stop: {', '.join(unprotected)}")
    if unknown_spec:
        return _gate(
            "gate-open-risk",
            "Open risk guard",
            True,
            f"risk unmeasured (no symbol specification): {', '.join(unknown_spec)}",
        )
    return _gate(
        "gate-open-risk",
        "Open risk guard",
        open_risk_percent > limit_percent,
        f"{_pct(open_risk_percent)} open of {_pct(limit_percent)} max",
    )


def correlation_gate(correlated_percent: float, limit_percent: float, key: tuple[str, str] | None) -> GateResult:
    where = f" on {key[0]} {key[1]}" if key else ""
    return _gate(
        "gate-correlation",
        "Correlated exposure guard",
        correlated_percent > limit_percent,
        f"{_pct(correlated_percent)} shared{where} of {_pct(limit_percent)} max",
    )


def max_trades_gate(trades_today: int | None, profile: RiskProfile) -> GateResult:
    if trades_today is None:
        return _gate("gate-max-trades", "Max trades/day", False, "n/a (observe)")
    return _gate(
        "gate-max-trades",
        "Max trades/day",
        trades_today >= profile.max_trades_per_day,
        f"{trades_today}/{profile.max_trades_per_day} today",
    )


def consecutive_loss_gate(consecutive_losses: int | None, profile: RiskProfile) -> GateResult:
    if consecutive_losses is None:
        return _gate("gate-consec-loss", "Consecutive losses", False, "n/a (observe)")
    return _gate(
        "gate-consec-loss",
        "Consecutive losses",
        consecutive_losses >= profile.max_consecutive_losses,
        f"{consecutive_losses}/{profile.max_consecutive_losses}",
    )


def position_limit_gate(open_positions: int, limits: PositionLimits) -> GateResult:
    return _gate(
        "gate-position-limit",
        "Position limit",
        open_positions >= limits.max_open_positions,
        f"{open_positions}/{limits.max_open_positions} open",
    )


def connection_gate(agent_connected: bool) -> GateResult:
    """An execution agent must be reachable before an order is approved. Deliberately not nullable: the link is
    always knowable, so an absent agent is a definite no, not missing data."""
    return _gate(
        "gate-connection",
        "Execution agent",
        not agent_connected,
        "connected" if agent_connected else "no agent connected",
    )


def spread_gate(spread: float | None, cap: float | None, *, require_tick: bool = False) -> GateResult:
    """No fixed spread limit by default (ADR 0015, amendement): the cost gate — spread relative to the stop —
    is what protects (``sizing.cost_ratio``). ``cap`` is an optional per-symbol ceiling, in price units."""
    if spread is None:
        if require_tick:
            return _gate("gate-spread", "Spread gate", True, "no live tick — spread unknown")
        return _gate("gate-spread", "Spread gate", False, "n/a (no tick)")
    if spread <= 0:
        return _gate("gate-spread", "Spread gate", True, f"invalid spread {spread:g}")
    if cap is None:
        return _gate("gate-spread", "Spread gate", False, f"{spread:g} (cost gate decides)")
    return _gate(
        "gate-spread",
        "Spread gate",
        spread > cap,
        f"{spread:g} {'>' if spread > cap else '<='} {cap:g} limit",
    )


def session_gate(in_window: bool, window_label: str | None) -> GateResult:
    detail = (
        f"{window_label} window open"
        if in_window and window_label
        else ("window open" if in_window else "outside the trading windows")
    )
    return _gate("gate-session", "Session filter", not in_window, detail)


def news_gate(releases: Sequence[UpcomingRelease] | None, now: datetime, policy: NewsPolicy) -> GateResult:
    """Fail closed. ``releases is None`` = calendar unknown or stale (never synced, FRED unreachable, bad key,
    last sync too old): the gate blocks. An empty but *known* calendar is not the same thing and stays open."""
    if releases is None:
        return _gate("gate-news", "News filter", True, "No calendar data — failing closed")
    if is_news_blackout(now, releases, policy.blackout_minutes):
        return _gate("gate-news", "News filter", True, f"Blackout ±{policy.blackout_minutes}min around a release")
    upcoming = next_release(now, releases)
    detail = (
        f"Next: {upcoming.label} at {upcoming.scheduled_at.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        if upcoming
        else "No upcoming release known"
    )
    return _gate("gate-news", "News filter", False, detail)


def symbol_gate(symbol: str, allowed: frozenset[str] | None) -> GateResult:
    ok = allowed is None or symbol in allowed
    return _gate("gate-symbol", "Symbol filter", not ok, f"{symbol} {'allowed' if ok else 'not allowed'}")
