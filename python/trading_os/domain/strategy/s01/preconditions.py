"""S01 pre-conditions that have no existing implementation to reuse: the killzone windows and the NY lunch cutoff, both stated in New
York local time and therefore DST-aware (port of ``lib/setup/preconditions.ts``). Everything else in S01's « Pré-conditions » (calendar,
lockouts) is read from the database by the strategy runtime; nothing here duplicates that.

The hours are the strategy's own (``S01Config.trading_windows``, ``S02Config.trading_windows``; ADR 0030) and are passed in: S01's
historical 02:00–05:00 / 07:00–10:00 are the default of this module, S02's 02:00–05:00 / 08:30–11:00 are its own. They are POSED, not
derived — the same status as S01's cost threshold (0.25): provisional until an observation sample says otherwise.

Faithful to the original, a weekend is not excluded here (the live gate is the Risk Engine's ``TradingWindow``, which is).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from trading_os.domain.market.calendar import UpcomingRelease, is_news_blackout
from trading_os.domain.market.sessions import (
    NY_TIME_ZONE,
    S01_TRADING_WINDOWS,
    TradingWindow,
    describe_trading_windows,
)
from trading_os.domain.strategy.s01.models import BlockedOutcome, SetupStage

NY_LUNCH_MINUTE = 12 * 60  # S01: « Aucune nouvelle position après 12:00 NY. »


def _ny_minutes_of_day(timestamp: datetime) -> int:
    local = timestamp.astimezone(NY_TIME_ZONE)
    return local.hour * 60 + local.minute


def is_in_killzone(timestamp: datetime, windows: Sequence[TradingWindow] = S01_TRADING_WINDOWS) -> bool:
    """True inside one of the strategy's windows, in New York local time (the zone moves them with daylight saving). The clock is read
    in New York and nowhere else: neither UTC nor the MT5 server's time ever meets a window."""
    local = timestamp.astimezone(NY_TIME_ZONE).time().replace(tzinfo=None)
    return any(window.start <= local < window.end for window in windows)


def is_past_ny_lunch(timestamp: datetime) -> bool:
    """True at or after 12:00 New York time — no new position, per S01."""
    return _ny_minutes_of_day(timestamp) >= NY_LUNCH_MINUTE


def blocking_precondition(
    now: datetime,
    *,
    releases: Sequence[UpcomingRelease] | None,
    blackout_minutes: int,
    lockout_active: bool,
    trades_today: int | None,
    max_trades_per_day: int,
    windows: Sequence[TradingWindow] = S01_TRADING_WINDOWS,
) -> BlockedOutcome | None:
    """The first of S01's five pre-conditions that does not hold, or ``None`` when all do (port of the checks of
    the former TypeScript detection worker, in its order): « si une seule manque, il n'y a pas de recherche ».

    ``now`` is the open time of the last candle evaluated (the original's convention, which keeps a replay reproducible). ``releases is
    None`` is a calendar that was never synced or is stale — unknown, and the pre-condition fails closed, as the news gate does.
    ``trades_today is None`` is a count the Risk Engine cannot establish yet; it is not guessed here (the Risk Engine's own gate
    decides when the proposal reaches it).
    """
    if not is_in_killzone(now, windows):
        return BlockedOutcome(
            stage=SetupStage.PRECONDITION_SESSION_WINDOW,
            detail=f"outside the strategy's trading windows (NY time): {describe_trading_windows(windows)}",
        )
    if is_past_ny_lunch(now):
        return BlockedOutcome(stage=SetupStage.PRECONDITION_NY_LUNCH, detail="past 12:00 NY, no new positions")
    if releases is None:
        return BlockedOutcome(
            stage=SetupStage.PRECONDITION_CALENDAR, detail="calendar never synced or stale — failing closed"
        )
    if is_news_blackout(now, releases, blackout_minutes):
        return BlockedOutcome(
            stage=SetupStage.PRECONDITION_CALENDAR,
            detail=f"within {blackout_minutes}min of a whitelisted FRED release",
        )
    if lockout_active:
        return BlockedOutcome(stage=SetupStage.PRECONDITION_LOCKOUT, detail="an active T02a/T02b lockout")
    if trades_today is not None and trades_today >= max_trades_per_day:
        return BlockedOutcome(
            stage=SetupStage.PRECONDITION_TRADES_LIMIT, detail=f"{trades_today}/{max_trades_per_day} trades today"
        )
    return None
