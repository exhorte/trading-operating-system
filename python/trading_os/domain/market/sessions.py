"""Sessions.

Two distinct notions, kept apart on purpose (audit C-16 / TD-17):

* ``SessionWindow`` — fixed UTC buckets used to *tag* timestamps for market context and attribution
  (port of ``lib/analysis/sessions.ts``);
* ``TradingWindow`` — the hours the trader actually trades, expressed in **New York local time** and therefore
  DST-aware (S01's killzones: London 02:00–05:00 and New York AM 07:00–10:00 NY, no new position after 12:00 NY).
  The risk engine's session gate reads these, not the UTC buckets.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time
from zoneinfo import ZoneInfo

from trading_os.domain.primitives import DomainModel, TradingSession

NY_TIME_ZONE = ZoneInfo("America/New_York")


class SessionWindow(DomainModel):
    session: TradingSession
    start_utc: str  # "HH:MM"
    end_utc: str  # "HH:MM", may wrap midnight
    trading_enabled: bool


# Pragmatic UTC buckets (not DST-aware) — context tagging only.
DEFAULT_SESSION_WINDOWS: tuple[SessionWindow, ...] = (
    SessionWindow(session=TradingSession.ASIA, start_utc="23:00", end_utc="07:00", trading_enabled=False),
    SessionWindow(session=TradingSession.LONDON, start_utc="07:00", end_utc="12:00", trading_enabled=True),
    SessionWindow(session=TradingSession.NEW_YORK_AM, start_utc="12:00", end_utc="16:00", trading_enabled=True),
    SessionWindow(session=TradingSession.NEW_YORK_PM, start_utc="16:00", end_utc="20:00", trading_enabled=False),
    SessionWindow(session=TradingSession.OFF_SESSION, start_utc="20:00", end_utc="23:00", trading_enabled=False),
)


def _minutes_of_day(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def _contains(window: SessionWindow, minutes: int) -> bool:
    start, end = _minutes_of_day(window.start_utc), _minutes_of_day(window.end_utc)
    if start <= end:
        return start <= minutes < end
    return minutes >= start or minutes < end  # wraps midnight


def session_for_timestamp(ts: datetime, windows: Sequence[SessionWindow] = DEFAULT_SESSION_WINDOWS) -> TradingSession:
    utc = ts.astimezone(ZoneInfo("UTC"))
    minutes = utc.hour * 60 + utc.minute
    for window in windows:
        if _contains(window, minutes):
            return window.session
    return TradingSession.OFF_SESSION


def session_enabled(session: TradingSession, windows: Sequence[SessionWindow] = DEFAULT_SESSION_WINDOWS) -> bool:
    for window in windows:
        if window.session == session:
            return window.trading_enabled
    return False


class TradingWindow(DomainModel):
    """A daily window in New York local time, ``[start, end)``. Weekends never count as open."""

    name: str
    start: time
    end: time

    def contains(self, ts: datetime) -> bool:
        local = ts.astimezone(NY_TIME_ZONE)
        if local.weekday() >= 5:  # Saturday/Sunday: no market (TD-08: the old gate counted them open)
            return False
        return self.start <= local.time().replace(tzinfo=None) < self.end


# S01 killzones, POSED not derived (fiche S01) — the user's trading hours.
DEFAULT_TRADING_WINDOWS: tuple[TradingWindow, ...] = (
    TradingWindow(name="london", start=time(2, 0), end=time(5, 0)),
    TradingWindow(name="new_york_am", start=time(7, 0), end=time(10, 0)),
)

NY_LUNCH = time(12, 0)


def in_trading_window(ts: datetime, windows: Sequence[TradingWindow] = DEFAULT_TRADING_WINDOWS) -> bool:
    return any(window.contains(ts) for window in windows)


def window_name_at(ts: datetime, windows: Sequence[TradingWindow] = DEFAULT_TRADING_WINDOWS) -> str | None:
    for window in windows:
        if window.contains(ts):
            return window.name
    return None


def past_ny_lunch(ts: datetime) -> bool:
    """S01: no new position at or after 12:00 New York time."""
    return ts.astimezone(NY_TIME_ZONE).time().replace(tzinfo=None) >= NY_LUNCH
