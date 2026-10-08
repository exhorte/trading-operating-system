"""The news calendar: FRED's release schedule, cached in the database, read by the news gate (T03).

Fail closed, by construction:

* **never synced is unknown, not empty.** The snapshot's ``releases`` is ``None`` until the cache holds something *and* a
  sync has completed; a stale sync (older than the account's ``calendar_max_age_hours``) is unknown too — the gate then
  blocks (``CalendarSnapshot.usable``);
* **a failed refresh never wipes the cache.** Each release is refreshed on its own; one that fails (bad key, FRED down, rate
  limit) keeps its last-known-good rows and does not block the others. The sync timestamp advances only when *every*
  release was refreshed — a calendar that is partly out of date is not « fresh »;
* **it survives a restart without a network**: ``start()`` publishes what the database holds before any request is made.

The blackout is symmetric (± minutes around a release), so a release that has *just passed* still matters: the snapshot keeps
releases for ``RETAIN`` after their time. (The previous stack kept them only by accident, between two six-hourly refreshes.)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from trading_os.domain.events import MarketCalendarUpdated
from trading_os.domain.market.calendar import FRED_WHITELIST, CalendarSnapshot, FredReleaseSpec, UpcomingRelease
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.infrastructure.database.repositories.market import NewsRepository
from trading_os.shared.errors import Unavailable
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.time import Clock, iso, parse_iso

logger = logging.getLogger(__name__)

REFRESH_INTERVAL = timedelta(hours=6)  # schedules are announced months ahead and almost never change
KEEP_PER_RELEASE = 3  # only the nearest few matter to the gate and the cockpit
RETAIN = timedelta(hours=3)  # a release that has passed still counts for the symmetric blackout


class CalendarClient(Protocol):
    async def fetch_upcoming(self, spec: FredReleaseSpec, now: datetime) -> list[datetime]: ...


@dataclass(frozen=True)
class RefreshResult:
    refreshed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: str | None = None  # why nothing was attempted (no API key)

    @property
    def complete(self) -> bool:
        return self.skipped is None and not self.failed


class NewsService:
    def __init__(
        self,
        *,
        repos: Repositories,
        events: EventDispatcher,
        clock: Clock,
        client: CalendarClient | None,
        whitelist: tuple[FredReleaseSpec, ...] = FRED_WHITELIST,
        interval: timedelta = REFRESH_INTERVAL,
    ) -> None:
        self._repos = repos
        self._events = events
        self._clock = clock
        self._client = client
        self._whitelist = whitelist
        self._interval = interval
        self._releases: list[UpcomingRelease] | None = None
        self._synced_at: datetime | None = None
        self._lock = asyncio.Lock()
        self.last_error: str | None = None
        self.last_attempt_at: datetime | None = None

    # ------------------------------------------------------------------------------------------ reading
    @property
    def configured(self) -> bool:
        """Whether a FRED key is available at all — without it the cache can only age."""
        return self._client is not None

    def snapshot(self) -> CalendarSnapshot:
        """What the news gate reads (``RiskService`` calls this on every evaluation: it is memory only)."""
        if self._releases is None:
            return CalendarSnapshot(releases=None, synced_at=self._synced_at)
        floor = self._clock.now() - RETAIN
        return CalendarSnapshot(
            releases=[r for r in self._releases if r.scheduled_at > floor], synced_at=self._synced_at
        )

    # ------------------------------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        """Load the cache and tell everyone what it holds, before any network attempt."""
        await self._load()
        await self._publish()

    async def refresh(self) -> RefreshResult:
        async with self._lock:
            now = self._clock.now()
            self.last_attempt_at = now
            if self._client is None:
                self.last_error = "FRED_API_KEY is not configured: the calendar cannot refresh and will age"
                logger.warning(self.last_error)
                return RefreshResult(skipped=self.last_error)
            refreshed: list[str] = []
            failed: list[str] = []
            for spec in self._whitelist:
                try:
                    instants = await self._client.fetch_upcoming(spec, now)
                    await self._repos.news.replace_upcoming(
                        spec.release_id, spec.label, instants[:KEEP_PER_RELEASE], now
                    )
                    refreshed.append(spec.label)
                except Unavailable as error:  # FRED down, bad key, rate limit — or the database
                    # One release failing must never wipe its cache nor block the others.
                    failed.append(spec.label)
                    logger.warning("FRED refresh failed for %s: %s", spec.label, error.safe_message)
                    self.last_error = error.safe_message
            result = RefreshResult(refreshed=refreshed, failed=failed)
            if result.complete:
                self.last_error = None
                await self._mark_synced(now)
            await self._load()
            await self._publish()
            return result

    async def run(self, stop: asyncio.Event) -> None:
        """Refresh now, then every ``interval``, until ``stop`` is set."""
        while not stop.is_set():
            try:
                await self.refresh()
            except Exception:  # the loop must outlive any single failure
                logger.exception("news calendar refresh crashed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._interval.total_seconds())

    # ------------------------------------------------------------------------------------------ internals
    async def _load(self) -> None:
        now = self._clock.now()
        try:
            releases = await self._repos.news.around(now, RETAIN)
            stored = await self._repos.state.get(NewsRepository.SYNC_KEY)
        except Unavailable as error:
            logger.warning(
                "news calendar: the cache could not be read (%s); keeping what is in memory", error.safe_message
            )
            return
        self._releases = releases
        self._synced_at = None
        if isinstance(stored, dict) and isinstance(stored.get("at"), str):
            with contextlib.suppress(ValueError):
                self._synced_at = parse_iso(stored["at"])

    async def _mark_synced(self, at: datetime) -> None:
        try:
            await self._repos.state.set(NewsRepository.SYNC_KEY, {"at": iso(at)})
        except Unavailable as error:
            self.last_error = error.safe_message
            logger.warning("news calendar: the sync time could not be recorded (%s)", error.safe_message)

    async def _publish(self) -> None:
        snapshot = self.snapshot()
        await self._events.publish(MarketCalendarUpdated(releases=snapshot.releases, synced_at=snapshot.synced_at))
