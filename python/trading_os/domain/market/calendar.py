"""Economic calendar for the news gate (T03).

The FRED whitelist *is* the impact classification — never add a source or an "impact" field elsewhere.
FRED returns only a calendar **date**; each release's long-standing publication time (BLS/BEA/Census 08:30 ET,
FOMC statement 14:00 ET) is combined with it and resolved to a UTC instant with the real EST/EDT offset of that
date. ISM is absent on purpose: no FRED release id exists for it.

Fail-closed, and stricter than before: an *unknown* calendar (never synced) blocks, and so does a **stale** one
(last successful sync older than ``max_age``) — the old gate treated a cache of only past rows as "nothing soon".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from trading_os.domain.primitives import DomainModel

EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class FredReleaseSpec:
    release_id: int
    label: str
    hour_et: int
    minute_et: int


FRED_WHITELIST: tuple[FredReleaseSpec, ...] = (
    FredReleaseSpec(10, "CPI US", 8, 30),
    FredReleaseSpec(50, "NFP US", 8, 30),
    FredReleaseSpec(54, "PCE US", 8, 30),
    FredReleaseSpec(9, "Retail Sales US", 8, 30),
    FredReleaseSpec(101, "FOMC", 14, 0),
)


def release_utc_instant(release_date: date, hour_et: int, minute_et: int) -> datetime:
    """UTC instant of ``release_date`` at ``hour_et:minute_et`` US Eastern (DST resolved for that very date)."""
    local = datetime(release_date.year, release_date.month, release_date.day, hour_et, minute_et, tzinfo=EASTERN)
    return local.astimezone(UTC)


class UpcomingRelease(DomainModel):
    release_id: int
    label: str
    scheduled_at: datetime


class CalendarSnapshot(DomainModel):
    """What the news gate reads. ``releases is None`` means *unknown* (never synced) — never an empty calendar."""

    releases: list[UpcomingRelease] | None
    synced_at: datetime | None = None

    def usable(self, now: datetime, max_age: timedelta) -> list[UpcomingRelease] | None:
        """The releases to trust, or ``None`` when the calendar is unknown or stale (gate then fails closed)."""
        if self.releases is None or self.synced_at is None:
            return None
        if now - self.synced_at > max_age:
            return None
        return list(self.releases)


def is_news_blackout(now: datetime, releases: Sequence[UpcomingRelease], window_minutes: int) -> bool:
    """Symmetric window: ±``window_minutes`` around any release."""
    window = timedelta(minutes=window_minutes)
    return any(abs(release.scheduled_at - now) <= window for release in releases)


def next_release(now: datetime, releases: Sequence[UpcomingRelease]) -> UpcomingRelease | None:
    """Soonest release at or after ``now``; ``None`` means none known, not none scheduled."""
    upcoming = [r for r in releases if r.scheduled_at >= now]
    return min(upcoming, key=lambda r: r.scheduled_at) if upcoming else None
