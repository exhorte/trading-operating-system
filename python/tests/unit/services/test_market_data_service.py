"""MarketDataService: the broker clock, quotes, closed bars announced once, a lossy-but-counted tick queue, and the
difference between a closed market and a dead feed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.support.harness import Harness
from tests.unit.services.test_accounts_service import exness, service
from trading_os.domain.events import CandleClosed, MarketTickReceived
from trading_os.domain.market.models import Tick
from trading_os.domain.primitives import Timeframe
from trading_os.infrastructure.database.pool import Database
from trading_os.services.accounts import AccountService
from trading_os.services.market_data import MarketDataService, TickWriter
from trading_os.shared.errors import Unavailable

pytestmark = pytest.mark.db


@pytest.fixture
async def h(db: Database) -> Harness:
    harness = Harness.create(db)
    harness.server_offset_minutes = 120  # a broker two hours ahead of UTC
    return harness


async def connected(h: Harness) -> tuple[AccountService, MarketDataService, str]:
    accounts = service(h)
    created = await accounts.create(exness())
    await accounts.connect(created.id)
    market = MarketDataService(
        accounts=accounts, repos=h.repos, events=h.events, clock=h.clock, tick_writer=TickWriter(h.repos.market)
    )
    return accounts, market, created.id


async def test_the_default_watchlist_follows_the_broker_naming_and_open_positions_are_added(h: Harness) -> None:
    _, market, account_id = await connected(h)
    assert market.watchlist(account_id) == ("EURUSDm", "XAUUSDm")
    market.watch_also(account_id, {"GBPUSDm", "EURUSDm"})
    assert market.watchlist(account_id) == ("EURUSDm", "XAUUSDm", "GBPUSDm")


async def test_preparing_learns_the_broker_clock_and_remembers_it(h: Harness) -> None:
    accounts, market, account_id = await connected(h)
    await market.prepare(account_id)
    session = accounts.session(account_id)
    assert session is not None and session.client.server_offset_minutes == 120
    assert await h.repos.state.get(f"server_offset.{account_id}") == {"minutes": 120}
    spec = market.spec(account_id, "EURUSDm")
    assert spec is not None and spec.tick_size == 0.00001
    # quotes carry true UTC, not the broker reading
    await market.poll_ticks(account_id)
    tick = market.tick(account_id, "EURUSDm")
    assert tick is not None and abs((tick.time - h.clock.now()).total_seconds()) < 2
    assert 0 < (market.spread(account_id, "EURUSDm") or 0) < 0.001


async def test_a_new_quote_is_announced_and_an_unchanged_one_is_not(h: Harness) -> None:
    _, market, account_id = await connected(h)
    assert await market.poll_ticks(account_id) == 2
    assert len(h.recorder.of(MarketTickReceived)) == 2
    assert await market.poll_ticks(account_id) == 0  # same clock, same quote: nothing new
    h.clock.advance(seconds=1)
    assert await market.poll_ticks(account_id) == 2
    assert {e.tick.symbol for e in h.recorder.of(MarketTickReceived)} == {"EURUSDm", "XAUUSDm"}


async def test_each_closed_bar_is_announced_once_and_stored(h: Harness) -> None:
    _, market, account_id = await connected(h)
    await market.prepare(account_id)  # backfills history without announcing it
    assert await market.poll_candles(account_id) == 0
    stored_before = await h.repos.market.last_candle_time("EURUSDm", Timeframe.M1)
    assert stored_before is not None

    h.clock.advance(minutes=1)
    assert await market.poll_candles(account_id) == 2  # one new closed bar per symbol
    assert await market.poll_candles(account_id) == 0  # not again
    announced = h.recorder.of(CandleClosed)
    assert {c.candle.symbol for c in announced} == {"EURUSDm", "XAUUSDm"}
    assert all(c.candle.closed and c.candle.timeframe is Timeframe.M1 for c in announced)
    assert await h.repos.market.last_candle_time("EURUSDm", Timeframe.M1) == stored_before + timedelta(minutes=1)

    h.clock.advance(minutes=3)
    assert await market.poll_candles(account_id) == 6  # three missed bars per symbol arrive in order
    times = [c.candle.open_time for c in h.recorder.of(CandleClosed) if c.candle.symbol == "EURUSDm"]
    assert times == sorted(times) and len(set(times)) == len(times)


async def test_the_feed_is_degraded_only_when_an_open_market_goes_quiet(h: Harness) -> None:
    _, market, account_id = await connected(h)
    assert market.feed_status(account_id, h.clock.now()) == (False, "market data not started")
    await market.poll_ticks(account_id)
    assert market.feed_status(account_id, h.clock.now())[0] is True
    h.clock.advance(seconds=90)
    fresh, detail = market.feed_status(account_id, h.clock.now())
    assert fresh is False and "90s" in detail
    saturday = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    assert market.feed_status(account_id, saturday) == (True, "market closed")


async def test_forgetting_an_account_drops_its_quotes(h: Harness) -> None:
    _, market, account_id = await connected(h)
    await market.poll_ticks(account_id)
    assert market.tick(account_id, "EURUSDm") is not None
    market.forget(account_id)
    assert market.tick(account_id, "EURUSDm") is None and market.spec(account_id, "EURUSDm") is None


# ------------------------------------------------------------------------------------------------------ tick writer


def tick(i: int) -> Tick:
    return Tick(symbol="EURUSDm", bid=1.1, ask=1.1001, time=datetime(2026, 10, 7, 12, 0, i, tzinfo=UTC))


async def test_ticks_are_written_in_batches(h: Harness) -> None:
    writer = TickWriter(h.repos.market, batch=3)
    for i in range(5):
        writer.offer(tick(i))
    await writer.flush()
    assert (writer.written, writer.queued, writer.dropped) == (3, 2, 0)
    await writer.flush()
    assert (writer.written, writer.queued) == (5, 0)
    assert await h.db.fetch_value("SELECT count(*) FROM ticks") == 5


async def test_a_full_queue_and_a_dead_database_lose_ticks_but_count_them(h: Harness) -> None:
    writer = TickWriter(h.repos.market, capacity=2)
    for i in range(4):
        writer.offer(tick(i))
    assert writer.dropped == 2 and writer.queued == 2

    class DownRepo:
        async def insert_ticks(self, ticks: object) -> None:
            raise Unavailable("database unavailable", code="database_unavailable")

    broken = TickWriter(DownRepo())  # type: ignore[arg-type]
    broken.offer(tick(0))
    broken.offer(tick(1))
    await broken.flush()
    assert broken.dropped == 2 and broken.written == 0 and broken.queued == 0
