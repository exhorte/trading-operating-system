"""S01 pre-conditions that have no existing implementation to reuse: the killzone windows and the NY lunch cutoff, both stated in New
York local time and therefore DST-aware (port of ``lib/setup/preconditions.ts``). Everything else in S01's « Pré-conditions » (calendar,
lockouts) is read from the database by the strategy runtime; nothing here duplicates that.

The killzone hour ranges are ICT-standard values, POSED not derived — the same status as S01's cost threshold (0.25): provisional until
an observation sample says otherwise. Neither S01 nor the framework document gives numeric hours for them.

Faithful to the original, a weekend is not excluded here (the live gate is the Risk Engine's ``TradingWindow``, which is).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from trading_os.domain.market.calendar import UpcomingRelease, is_news_blackout
from trading_os.domain.market.sessions import NY_TIME_ZONE
from trading_os.domain.strategy.s01.models import BlockedOutcome, SetupStage

# [start, end) of the New York day, in minutes, per killzone.
KILLZONE_WINDOWS_NY_MINUTES: dict[str, tuple[int, int]] = {
    "london": (2 * 60, 5 * 60),  # 02:00-05:00 NY
    "new_york_am": (7 * 60, 10 * 60),  # 07:00-10:00 NY
}

NY_LUNCH_MINUTE = 12 * 60  # S01: « Aucune nouvelle position après 12:00 NY. »


def _ny_minutes_of_day(timestamp: datetime) -> int:
    local = timestamp.astimezone(NY_TIME_ZONE)
    return local.hour * 60 + local.minute


def is_in_killzone(timestamp: datetime) -> bool:
    """True during the London or New York AM killzone, in New York local time."""
    minutes = _ny_minutes_of_day(timestamp)
    return any(start <= minutes < end for start, end in KILLZONE_WINDOWS_NY_MINUTES.values())


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
) -> BlockedOutcome | None:
    """The first of S01's five pre-conditions that does not hold, or ``None`` when all do (port of the checks of
    the former TypeScript detection worker, in its order): « si une seule manque, il n'y a pas de recherche ».

    ``now`` is the open time of the last candle evaluated (the original's convention, which keeps a replay reproducible). ``releases is
    None`` is a calendar that was never synced or is stale — unknown, and the pre-condition fails closed, as the news gate does.
    ``trades_today is None`` is a count the Risk Engine cannot establish yet; it is not guessed here (the Risk Engine's own gate
    decides when the proposal reaches it).
    """
    if not is_in_killzone(now):
        return BlockedOutcome(
            stage=SetupStage.PRECONDITION_SESSION_WINDOW, detail="outside the London/NY AM killzone (NY time)"
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
