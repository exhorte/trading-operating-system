"""Sessions.

Two distinct notions, kept apart on purpose (audit C-16 / TD-17):

* ``SessionWindow`` — fixed UTC buckets used to *tag* timestamps for market context and attribution
  (port of ``lib/analysis/sessions.ts``);
* ``TradingWindow`` — the hours the trader actually trades, expressed in **New York local time** and therefore
  DST-aware. The risk engine's session gate reads these, not the UTC buckets.

Time zones are never mixed (ADR 0030): a trading window is read in ``America/New_York`` — the zone's own rules move it with the
daylight-saving change, twice a year, with no offset written anywhere — a timestamp is an aware datetime (UTC at the edges), and the
MT5 server's clock is converted at the terminal's edge, never compared with a window. Each strategy owns its windows
(``S01Config.trading_windows``, ``S02Config.trading_windows``); the account's windows are the envelope the Risk Engine's gate enforces.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time
from itertools import pairwise
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


# S01's killzones, POSED not derived (fiche S01) — the historical hours of the first strategy. They are S01's own configuration
# (``S01Config.trading_windows``) and nothing else's: S02 does not inherit them (ADR 0030).
S01_TRADING_WINDOWS: tuple[TradingWindow, ...] = (
    TradingWindow(name="london", start=time(2, 0), end=time(5, 0)),
    TradingWindow(name="new_york_am", start=time(7, 0), end=time(10, 0)),
)

# S02's default hours (ADR 0030, the user's decision of 2026-11-01): New York AM 08:30–11:00 NY — the execution window of notes N4, N5
# and N6 (08:30 is the hour of the economic releases) — and the London killzone 02:00–05:00 NY, kept as the notes give it (N6) and as
# the code already had it. Nothing else: the afternoon profile of N4 (13:30–16:00) is not part of S02's defaults.
S02_TRADING_WINDOWS: tuple[TradingWindow, ...] = (
    TradingWindow(name="london", start=time(2, 0), end=time(5, 0)),
    TradingWindow(name="new_york_am", start=time(8, 30), end=time(11, 0)),
)

# The envelope a NEW account starts with: every hour at least one strategy may trade, nothing more — London 02:00–05:00 and New York
# 07:00–11:00 (S01 from 07:00, S02 until 11:00). Each strategy keeps to its own windows inside it. An account created before ADR 0030
# keeps the windows it stored; widening them is the user's gesture, in Settings.
ACCOUNT_TRADING_WINDOWS: tuple[TradingWindow, ...] = (
    TradingWindow(name="london", start=time(2, 0), end=time(5, 0)),
    TradingWindow(name="new_york_am", start=time(7, 0), end=time(11, 0)),
)

# What the helpers below assume when no windows are given: the historical S01 hours (kept so that code and tests written for S01
# read exactly as before). A strategy passes its own.
DEFAULT_TRADING_WINDOWS = S01_TRADING_WINDOWS

NY_LUNCH = time(12, 0)


def parse_trading_windows(spec: str) -> tuple[TradingWindow, ...]:
    """Windows from text, the form the settings take: ``"london=02:00-05:00,new_york_am=08:30-11:00"`` (New York local time).
    Raises ``ValueError`` — never a guess — for anything malformed, a window that ends before it starts, a repeated name or windows
    that overlap."""
    windows: list[TradingWindow] = []
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        name, separator, hours = part.partition("=")
        start_text, dash, end_text = hours.partition("-")
        if not (separator and dash and name.strip()):
            raise ValueError(f"a window is written name=HH:MM-HH:MM, got {part!r}")
        try:
            start, end = time.fromisoformat(start_text.strip()), time.fromisoformat(end_text.strip())
        except ValueError as error:
            raise ValueError(f"a window's hours are HH:MM, got {part!r}") from error
        windows.append(TradingWindow(name=name.strip(), start=start, end=end))
    return validate_trading_windows(tuple(windows))


def validate_trading_windows(windows: Sequence[TradingWindow]) -> tuple[TradingWindow, ...]:
    """The windows as they are, or ``ValueError``: at least one, each ending after it starts, no name twice, none overlapping."""
    if not windows:
        raise ValueError("at least one trading window is needed")
    names = [w.name for w in windows]
    if len(set(names)) != len(names):
        raise ValueError(f"a window name is used twice: {names}")
    for window in windows:
        if not window.start < window.end:
            raise ValueError(f"window {window.name!r} must end after it starts ({window.start}–{window.end})")
    ordered = sorted(windows, key=lambda w: w.start)
    for before, after in pairwise(ordered):
        if after.start < before.end:
            raise ValueError(f"windows {before.name!r} and {after.name!r} overlap")
    return tuple(windows)


def describe_trading_windows(windows: Sequence[TradingWindow]) -> str:
    """``london 02:00–05:00, new_york_am 08:30–11:00`` — what a refusal or a report says about the hours in force."""
    return ", ".join(f"{w.name} {w.start:%H:%M}–{w.end:%H:%M}" for w in windows)


def in_trading_window(ts: datetime, windows: Sequence[TradingWindow] = DEFAULT_TRADING_WINDOWS) -> bool:
    return any(window.contains(ts) for window in windows)


def window_name_at(ts: datetime, windows: Sequence[TradingWindow] = DEFAULT_TRADING_WINDOWS) -> str | None:
    for window in windows:
        if window.contains(ts):
            return window.name
    return None


def minutes_until_window_end(ts: datetime, windows: Sequence[TradingWindow] = DEFAULT_TRADING_WINDOWS) -> float | None:
    """Minutes left before the window that contains ``ts`` closes, or ``None`` outside every window (and on weekends)."""
    local = ts.astimezone(NY_TIME_ZONE)
    for window in windows:
        if window.contains(ts):
            end = datetime.combine(local.date(), window.end, tzinfo=NY_TIME_ZONE)
            return (end - local).total_seconds() / 60
    return None


def past_ny_lunch(ts: datetime) -> bool:
    """S01: no new position at or after 12:00 New York time."""
    return ts.astimezone(NY_TIME_ZONE).time().replace(tzinfo=None) >= NY_LUNCH
