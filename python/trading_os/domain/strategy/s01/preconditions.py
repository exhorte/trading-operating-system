"""S01 pre-conditions that have no existing implementation to reuse: the killzone windows and the NY lunch cutoff, both stated in New
York local time and therefore DST-aware (port of ``lib/setup/preconditions.ts``). Everything else in S01's « Pré-conditions » (calendar,
lockouts) is read from the database by the strategy runtime; nothing here duplicates that.

The killzone hour ranges are ICT-standard values, POSED not derived — the same status as S01's cost threshold (0.25): provisional until
an observation sample says otherwise. Neither S01 nor the framework document gives numeric hours for them.

Faithful to the original, a weekend is not excluded here (the live gate is the Risk Engine's ``TradingWindow``, which is).
"""

from __future__ import annotations

from datetime import datetime

from trading_os.domain.market.sessions import NY_TIME_ZONE

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
