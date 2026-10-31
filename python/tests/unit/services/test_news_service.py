"""NewsService against a real database: a calendar that is unknown until it has really synced, that survives a restart and a
FRED outage, and that never lets a failure wipe what it knew."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from tests.support.harness import Harness
from trading_os.domain.events import MarketCalendarUpdated
from trading_os.domain.market.calendar import FRED_WHITELIST, FredReleaseSpec, is_news_blackout
from trading_os.infrastructure.database.pool import Database
from trading_os.infrastructure.database.repositories.market import NewsRepository
from trading_os.infrastructure.news.fred import FredError
from trading_os.services.news import KEEP_PER_RELEASE, NewsService
from trading_os.shared.errors import Unavailable

pytestmark = pytest.mark.db

MAX_AGE = timedelta(hours=48)  # NewsPolicy.calendar_max_age_hours
LABELS = [spec.label for spec in FRED_WHITELIST]


@dataclass
class FakeFred:
    """A FRED that returns canned instants per release id, or fails for some of them."""

    schedule: dict[int, list[datetime]] = field(default_factory=dict)
    failing: set[int] = field(default_factory=set)
    calls: list[int] = field(default_factory=list)

    async def fetch_upcoming(self, spec: FredReleaseSpec, now: datetime) -> list[datetime]:
        self.calls.append(spec.release_id)
        if spec.release_id in self.failing:
            raise FredError(f"FRED answered HTTP 500 for release {spec.release_id}")
        return sorted(t for t in self.schedule.get(spec.release_id, []) if t >= now)


@pytest.fixture
async def h(db: Database) -> Harness:
    return Harness.create(db)


def service(h: Harness, fred: FakeFred | None) -> NewsService:
    return NewsService(repos=h.repos, events=h.events, clock=h.clock, client=fred)


def week_ahead(h: Harness, hours: int = 24) -> dict[int, list[datetime]]:
    """Five releases, four dates each (more than the service keeps)."""
    now = h.clock.now()
    return {
        spec.release_id: [now + timedelta(hours=hours * (1 + i) + spec.release_id) for i in range(4)]
        for spec in FRED_WHITELIST
    }


async def test_a_calendar_that_never_synced_is_unknown_not_empty(h: Harness) -> None:
    news = service(h, FakeFred())
    await news.start()
    snapshot = news.snapshot()
    assert snapshot.releases is None and snapshot.synced_at is None
    assert snapshot.usable(h.clock.now(), MAX_AGE) is None  # the news gate fails closed
    assert h.recorder.of(MarketCalendarUpdated)[-1].releases is None


async def test_a_refresh_caches_the_nearest_releases_and_makes_the_calendar_usable(h: Harness) -> None:
    fred = FakeFred(week_ahead(h))
    news = service(h, fred)
    await news.start()
    result = await news.refresh()
    assert result.complete and sorted(result.refreshed) == sorted(LABELS) and result.failed == []
    snapshot = news.snapshot()
    assert snapshot.synced_at == h.clock.now()
    releases = snapshot.usable(h.clock.now(), MAX_AGE)
    assert releases is not None and len(releases) == KEEP_PER_RELEASE * len(FRED_WHITELIST)
    assert [r.scheduled_at for r in releases] == sorted(r.scheduled_at for r in releases)
    assert h.recorder.of(MarketCalendarUpdated)[-1].synced_at == h.clock.now()
    assert news.last_error is None


async def test_the_cache_survives_a_restart_with_no_network(h: Harness) -> None:
    await service(h, FakeFred(week_ahead(h))).refresh()
    h.clock.advance(hours=2)
    restarted = service(h, None)  # no FRED key at all after the restart
    await restarted.start()
    assert restarted.snapshot().usable(h.clock.now(), MAX_AGE) is not None
    assert h.recorder.of(MarketCalendarUpdated)[-1].releases  # told before any request could be made


async def test_one_failing_release_keeps_its_cache_and_does_not_block_the_others(h: Harness) -> None:
    fred = FakeFred(week_ahead(h))
    news = service(h, fred)
    await news.refresh()
    before = {
        r.release_id: [x.scheduled_at for x in news.snapshot().releases or [] if x.release_id == r.release_id]
        for r in FRED_WHITELIST
    }
    synced_before = news.snapshot().synced_at

    h.clock.advance(hours=6)
    cpi = FRED_WHITELIST[0].release_id
    fred.failing = {cpi}
    fred.schedule = {
        rid: [t + timedelta(hours=1) for t in times] for rid, times in fred.schedule.items()
    }  # FRED moved them
    result = await news.refresh()
    assert not result.complete and result.failed == [FRED_WHITELIST[0].label]
    assert FRED_WHITELIST[0].label not in result.refreshed and len(result.refreshed) == len(FRED_WHITELIST) - 1

    after = news.snapshot()
    cpi_rows = [r.scheduled_at for r in after.releases or [] if r.release_id == cpi]
    assert cpi_rows == before[cpi]  # last-known-good, not wiped
    other = FRED_WHITELIST[1].release_id
    assert [r.scheduled_at for r in after.releases or [] if r.release_id == other] != before[
        other
    ]  # the others moved on
    assert after.synced_at == synced_before  # a partly refreshed calendar is not « fresh »
    assert news.last_error is not None and "HTTP 500" in news.last_error


async def test_a_calendar_whose_sync_is_too_old_is_unknown_again(h: Harness) -> None:
    fred = FakeFred(week_ahead(h, hours=24 * 30))  # releases far in the future, so only the sync age matters
    news = service(h, fred)
    await news.refresh()
    h.clock.advance(hours=47)
    assert news.snapshot().usable(h.clock.now(), MAX_AGE) is not None
    h.clock.advance(hours=2)
    assert news.snapshot().usable(h.clock.now(), MAX_AGE) is None  # FRED has been unreachable for two days: gate closed


async def test_without_an_api_key_nothing_is_attempted_and_the_calendar_only_ages(h: Harness) -> None:
    news = service(h, None)
    await news.start()
    result = await news.refresh()
    assert result.skipped is not None and "FRED_API_KEY" in result.skipped and not news.configured
    assert news.snapshot().usable(h.clock.now(), MAX_AGE) is None
    assert news.last_error is not None


async def test_a_release_that_just_passed_still_counts_for_the_symmetric_blackout(h: Harness) -> None:
    now = h.clock.now()
    fred = FakeFred({10: [now + timedelta(minutes=5)]})
    news = service(h, fred)
    await news.refresh()
    fred.schedule = {}  # the release is now past; FRED lists nothing more
    h.clock.advance(minutes=20)  # 15 minutes after the release
    releases = news.snapshot().releases
    assert releases and is_news_blackout(h.clock.now(), releases, 30)
    h.clock.advance(hours=4)  # long gone: dropped from the snapshot
    assert not news.snapshot().releases


async def test_a_rescheduled_release_replaces_the_old_date_instead_of_sitting_next_to_it(h: Harness) -> None:
    now = h.clock.now()
    fred = FakeFred({50: [now + timedelta(days=3)]})
    news = service(h, fred)
    await news.refresh()
    fred.schedule = {50: [now + timedelta(days=5)]}
    await news.refresh()
    dates = [r.scheduled_at for r in news.snapshot().releases or [] if r.release_id == 50]
    assert dates == [now + timedelta(days=5)]


async def test_a_database_that_cannot_be_read_keeps_what_is_in_memory(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    news = service(h, FakeFred(week_ahead(h)))
    await news.refresh()
    known = news.snapshot()

    async def broken(*args: object, **kwargs: object) -> None:
        raise Unavailable("database unavailable", code="database_unavailable")

    monkeypatch.setattr(h.repos.news, "around", broken)
    await news.start()  # reloading fails; the gate keeps the last good calendar rather than going blind
    assert news.snapshot().releases == known.releases and news.snapshot().synced_at == known.synced_at


async def test_the_sync_time_is_stored_where_the_gate_can_find_it_after_a_restart(h: Harness) -> None:
    await service(h, FakeFred(week_ahead(h))).refresh()
    stored = await h.repos.state.get(NewsRepository.SYNC_KEY)
    assert stored is not None and stored["at"].endswith("Z")
