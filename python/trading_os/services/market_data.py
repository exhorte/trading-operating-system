"""Market data: the only source of quotes, bars and symbol specifications for the rest of the core (MT5 is the primary and
only source — no vendor data).

* One poll loop per connected account (the scheduler calls ``poll_ticks`` every second and ``poll_candles`` every few).
* Quotes are broadcast to the cockpit but **persisted through a bounded queue**: if the database is slow or down, ticks are
  dropped and *counted* (``TickWriter.dropped``, surfaced in the health) — a tick is never worth blocking the core for.
* Bars: the closed ones are upserted to the database and announced once (``CandleClosed``), the forming one never is.
* The broker's clock is measured from a fresh tick (``Mt5Client.measure_server_offset``) before any timestamp is trusted,
  and the last value is persisted so a weekend start (stale tick, nothing to measure) still has one.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from trading_os.domain.accounts.models import Account
from trading_os.domain.events import CandleClosed, MarketTickReceived
from trading_os.domain.market.hours import is_market_open
from trading_os.domain.market.models import Candle, SymbolSpec, Tick
from trading_os.domain.market.symbols import to_canonical
from trading_os.domain.primitives import Timeframe
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.infrastructure.database.repositories.market import MarketRepository
from trading_os.infrastructure.mt5.protocol import WorkerError
from trading_os.services.accounts import AccountService
from trading_os.shared.errors import TradingOsError, Unavailable
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)

DEFAULT_CANONICAL_WATCH = ("EURUSD", "XAUUSD")
OFFSET_KEY = "server_offset.{account_id}"
BACKFILL_M1 = 1500  # about a day of M1 bars: the strategy needs context the moment it starts
FRESH_FOR = timedelta(seconds=30)  # an open market that gave no new quote for this long is a degraded feed


class TickWriter:
    """Bounded, lossy, counted. ``offer`` never blocks and never raises."""

    def __init__(self, repo: MarketRepository, *, capacity: int = 10_000, batch: int = 500) -> None:
        self._repo = repo
        self._queue: asyncio.Queue[Tick] = asyncio.Queue(maxsize=capacity)
        self._batch = batch
        self.written = 0
        self.dropped = 0

    @property
    def queued(self) -> int:
        return self._queue.qsize()

    def offer(self, tick: Tick) -> None:
        try:
            self._queue.put_nowait(tick)
        except asyncio.QueueFull:
            self.dropped += 1

    async def flush(self) -> None:
        batch: list[Tick] = []
        while len(batch) < self._batch and not self._queue.empty():
            batch.append(self._queue.get_nowait())
        if not batch:
            return
        try:
            await self._repo.insert_ticks(batch)
            self.written += len(batch)
        except TradingOsError:
            self.dropped += len(batch)  # the database is down: lost, and said so

    async def run(self, interval: float = 1.0) -> None:
        while True:
            await asyncio.sleep(interval)
            await self.flush()


@dataclass
class _AccountFeed:
    last_candle: dict[tuple[str, Timeframe], datetime] = field(default_factory=dict)
    prepared: bool = False
    last_tick_poll: datetime | None = None
    last_new_tick: dict[str, datetime] = field(default_factory=dict)


class MarketDataService:
    def __init__(
        self,
        *,
        accounts: AccountService,
        repos: Repositories,
        events: EventDispatcher,
        clock: Clock,
        tick_writer: TickWriter | None = None,
        timeframes: tuple[Timeframe, ...] = (Timeframe.M1,),
    ) -> None:
        self._accounts = accounts
        self._repos = repos
        self._events = events
        self._clock = clock
        self._writer = tick_writer
        self._timeframes = timeframes
        self._ticks: dict[tuple[str, str], Tick] = {}
        self._specs: dict[tuple[str, str], SymbolSpec] = {}
        self._feeds: dict[str, _AccountFeed] = {}
        self._extra: dict[str, set[str]] = {}

    # ------------------------------------------------------------------------------------------ what to watch
    @staticmethod
    def default_watchlist(account: Account) -> tuple[str, ...]:
        if account.trading_rules.allowed_symbols:
            return account.trading_rules.allowed_symbols
        return tuple(f"{symbol}{account.symbol_suffix}" for symbol in DEFAULT_CANONICAL_WATCH)

    def watch_also(self, account_id: str, symbols: set[str]) -> None:
        """Symbols with an open position are always watched, whatever the watchlist says."""
        self._extra[account_id] = set(symbols)

    def watchlist(self, account_id: str) -> tuple[str, ...]:
        session = self._accounts.session(account_id)
        if session is None:
            return ()
        names = dict.fromkeys([*self.default_watchlist(session.account), *sorted(self._extra.get(account_id, ()))])
        return tuple(names)

    # ------------------------------------------------------------------------------------------ preparation
    async def prepare(self, account_id: str) -> None:
        """Once per connection: select the symbols, learn the broker's clock, load the specifications, backfill bars."""
        session = self._accounts.session(account_id)
        if session is None:
            return
        client = session.client
        feed = self._feeds.setdefault(account_id, _AccountFeed())
        names = self.watchlist(account_id)
        for name in names:
            with contextlib.suppress(WorkerError, Unavailable):
                await client.select_symbol(name)
        persisted = await self._safe_state(OFFSET_KEY.format(account_id=account_id))
        if isinstance(persisted, dict) and isinstance(persisted.get("minutes"), int):
            client.use_known_offset(persisted["minutes"])
        for name in names:
            try:
                before = client.server_offset_minutes
                measured = await client.measure_server_offset(name)
            except (WorkerError, Unavailable):
                continue
            if measured is not None and measured != before:
                await self._remember_offset(account_id, measured)
            if client.offset_known:
                break
        for name in names:
            await self.require_spec(account_id, name)
            for timeframe in self._timeframes:
                await self._backfill(account_id, name, timeframe)
        feed.prepared = True

    async def _safe_state(self, key: str) -> object | None:
        try:
            return await self._repos.state.get(key)
        except Unavailable:
            return None

    async def _remember_offset(self, account_id: str, minutes: int) -> None:
        with contextlib.suppress(Unavailable):
            await self._repos.state.set(OFFSET_KEY.format(account_id=account_id), {"minutes": minutes})

    async def _backfill(self, account_id: str, symbol: str, timeframe: Timeframe) -> None:
        session = self._accounts.session(account_id)
        if session is None:
            return
        try:
            candles = await session.client.candles(symbol, timeframe, BACKFILL_M1)
        except (WorkerError, Unavailable):
            return
        closed = [c for c in candles if c.closed]
        if closed:
            with contextlib.suppress(Unavailable):
                await self._repos.market.upsert_candles(closed)
            self._feeds[account_id].last_candle[(symbol, timeframe)] = closed[-1].open_time

    # ------------------------------------------------------------------------------------------ quotes
    async def poll_ticks(self, account_id: str) -> int:
        """Fetch the latest quote of every watched symbol. Returns how many were *new* (a quiet market repeats itself)."""
        session = self._accounts.session(account_id)
        if session is None:
            return 0
        feed = self._feeds.setdefault(account_id, _AccountFeed())
        if not feed.prepared:
            await self.prepare(account_id)
        fresh = 0
        for name in self.watchlist(account_id):
            try:
                tick = await session.client.tick(name)
            except (WorkerError, Unavailable):
                continue
            if tick is None:
                continue
            previous = self._ticks.get((account_id, name))
            self._ticks[(account_id, name)] = tick
            if previous is not None and previous.time == tick.time and previous.bid == tick.bid:
                continue
            fresh += 1
            feed.last_new_tick[name] = self._clock.now()
            if self._writer is not None:
                self._writer.offer(tick)
            await self._events.publish(MarketTickReceived(account_id=account_id, tick=tick))
        feed.last_tick_poll = self._clock.now()
        return fresh

    async def poll_candles(self, account_id: str) -> int:
        """Announce each newly closed bar exactly once, oldest first."""
        session = self._accounts.session(account_id)
        if session is None:
            return 0
        feed = self._feeds.setdefault(account_id, _AccountFeed())
        announced = 0
        for name in self.watchlist(account_id):
            for timeframe in self._timeframes:
                try:
                    candles = await session.client.candles(name, timeframe, 5)
                except (WorkerError, Unavailable):
                    continue
                last = feed.last_candle.get((name, timeframe))
                new = [c for c in candles if c.closed and (last is None or c.open_time > last)]
                if not new:
                    continue
                with contextlib.suppress(Unavailable):
                    await self._repos.market.upsert_candles(new)
                for candle in new:
                    await self._events.publish(CandleClosed(account_id=account_id, candle=candle))
                    announced += 1
                feed.last_candle[(name, timeframe)] = new[-1].open_time
        return announced

    async def recent_candles(self, account_id: str, symbol: str, timeframe: Timeframe, count: int) -> list[Candle]:
        session = self._accounts.session(account_id)
        if session is None:
            return []
        return await session.client.candles(symbol, timeframe, count)

    # ------------------------------------------------------------------------------------------ reading
    def tick(self, account_id: str, symbol: str) -> Tick | None:
        return self._ticks.get((account_id, symbol))

    def spread(self, account_id: str, symbol: str) -> float | None:
        tick = self.tick(account_id, symbol)
        return tick.spread if tick else None

    def spec(self, account_id: str, symbol: str) -> SymbolSpec | None:
        return self._specs.get((account_id, symbol))

    async def require_spec(self, account_id: str, symbol: str) -> SymbolSpec | None:
        cached = self._specs.get((account_id, symbol))
        if cached is not None:
            return cached
        session = self._accounts.session(account_id)
        if session is None:
            return None
        try:
            spec = await session.client.symbol_spec(symbol)
        except (WorkerError, Unavailable):
            return None
        if spec is not None:
            self._specs[(account_id, symbol)] = spec
        return spec

    def specs(self, account_id: str) -> dict[str, SymbolSpec]:
        return {symbol: spec for (acct, symbol), spec in self._specs.items() if acct == account_id}

    def forget(self, account_id: str) -> None:
        """Drop everything cached for an account (it disconnected): stale quotes must not outlive the link."""
        self._feeds.pop(account_id, None)
        self._extra.pop(account_id, None)
        for cache in (self._ticks, self._specs):
            for key in [k for k in cache if k[0] == account_id]:
                del cache[key]

    # ------------------------------------------------------------------------------------------ health
    def feed_status(self, account_id: str, now: datetime) -> tuple[bool, str]:
        """(fresh, detail). A closed market is fresh by definition; an open one needs a new quote within ``FRESH_FOR``
        for at least one watched symbol."""
        feed = self._feeds.get(account_id)
        names = self.watchlist(account_id)
        if feed is None or not feed.prepared or not names:
            return False, "market data not started"
        if not any(is_market_open(to_canonical(name), now) for name in names):
            return True, "market closed"
        newest = max(feed.last_new_tick.values(), default=None)
        if newest is None:
            return False, "no quote received yet"
        age = now - newest
        return age <= FRESH_FOR, f"last new quote {age.total_seconds():.0f}s ago"
