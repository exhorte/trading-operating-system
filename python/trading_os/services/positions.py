"""Positions: what the account holds, and the facts of every position opened or closed.

One poll per connected account (every ~2 s): account figures, open positions, pending orders. From the difference between
two polls this service derives the lifecycle facts the rest of the core lives on — and persists them *as they happen*:

* **opened** — first time a position identifier is seen (``position_opens``): the trade counts once, at its real open time;
* **closed** — an identifier that disappeared, read back from the deal history (net P&L = profit + commission + swap over
  every deal, volume-weighted exit price). The history can lag the position list by a moment, so a close is retried;
* **modified** — volume, stop or target changed;
* **missed round trips** — opened *and* closed between two polls (a fast stop-out): rebuilt from the deal history so the
  trade count and the loss streak never under-count.

Positions are keyed by MT5's POSITION_IDENTIFIER, never the ticket (the two diverge on broker service operations).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from trading_os.domain.accounts.models import AccountSnapshot
from trading_os.domain.events import (
    AccountSnapshotUpdated,
    PositionClosed,
    PositionModified,
    PositionOpened,
    PositionsSnapshotUpdated,
)
from trading_os.domain.positions.models import ClosedTrade, PendingOrder, Position
from trading_os.domain.risk.trading_day import resolve_today_start_utc
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.infrastructure.mt5.client import Mt5Client
from trading_os.infrastructure.mt5.mt5_semantics import (
    ClosedFact,
    Deal,
    closed_fact,
    missed_round_trip_ids,
    opened_fact_from_deal,
    scan_window,
)
from trading_os.infrastructure.mt5.protocol import WorkerError
from trading_os.services.accounts import AccountService
from trading_os.services.market_data import MarketDataService
from trading_os.shared.errors import Unavailable
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)

DEAL_ENTRY_IN = 0
MAX_CLOSE_ATTEMPTS = 6  # deal history normally catches up within a poll or two

Enricher = Callable[[AccountSnapshot, list[Position]], Awaitable[AccountSnapshot]]
Modifiable = Literal["volume", "stop_loss", "take_profit"]


@dataclass
class _State:
    baselined: bool = False
    known: set[str] = field(default_factory=set)
    by_id: dict[str, Position] = field(default_factory=dict)
    pending_close: dict[str, int] = field(default_factory=dict)  # position id → attempts so far
    last_deal_scan: datetime | None = None
    snapshot: AccountSnapshot | None = None
    positions: list[Position] = field(default_factory=list)
    orders: list[PendingOrder] = field(default_factory=list)
    updated_at: datetime | None = None
    failures: int = 0
    last_error: str | None = None
    terminal_connected: bool = False  # the terminal's own link to its trade server
    terminal_trade_allowed: bool = False


class PositionService:
    def __init__(
        self,
        *,
        accounts: AccountService,
        repos: Repositories,
        events: EventDispatcher,
        clock: Clock,
        market: MarketDataService,
        enricher: Enricher | None = None,
    ) -> None:
        self._accounts = accounts
        self._repos = repos
        self._events = events
        self._clock = clock
        self._market = market
        self._enricher = enricher
        self._state: dict[str, _State] = {}

    def set_enricher(self, enricher: Enricher) -> None:
        self._enricher = enricher

    # ------------------------------------------------------------------------------------------ reading
    def snapshot(self, account_id: str) -> AccountSnapshot | None:
        st = self._state.get(account_id)
        return st.snapshot if st else None

    def positions(self, account_id: str) -> list[Position]:
        st = self._state.get(account_id)
        return list(st.positions) if st else []

    def orders(self, account_id: str) -> list[PendingOrder]:
        st = self._state.get(account_id)
        return list(st.orders) if st else []

    def updated_at(self, account_id: str) -> datetime | None:
        st = self._state.get(account_id)
        return st.updated_at if st else None

    def failures(self, account_id: str) -> tuple[int, str | None]:
        st = self._state.get(account_id)
        return (st.failures, st.last_error) if st else (0, None)

    def baselined(self, account_id: str) -> bool:
        st = self._state.get(account_id)
        return bool(st and st.baselined)

    def terminal_connected(self, account_id: str) -> bool:
        st = self._state.get(account_id)
        return bool(st and st.terminal_connected)

    def open_count(self, account_id: str) -> int:
        return len(self.positions(account_id))

    def total_open_count(self) -> int:
        return sum(len(st.positions) for st in self._state.values())

    async def guard(self, account_id: str) -> str | None:
        """For ``AccountService``: refuse to switch away from, or drop, an account that still has exposure."""
        st = self._state.get(account_id)
        if st is None:
            return None
        parts = []
        if st.positions:
            parts.append(f"{len(st.positions)} open position(s)")
        if st.orders:
            parts.append(f"{len(st.orders)} pending order(s)")
        return ", ".join(parts) or None

    def forget(self, account_id: str) -> None:
        self._state.pop(account_id, None)

    # ------------------------------------------------------------------------------------------ polling
    async def poll(self, account_id: str) -> bool:
        """One cycle. False when the terminal could not be read (the snapshot ages; the supervisor decides what that means)."""
        session = self._accounts.session(account_id)
        if session is None:
            return False
        st = self._state.setdefault(account_id, _State())
        client = session.client
        try:
            info = await client.account_info()
            terminal = await client.terminal_info()
            positions = await client.positions()
            orders = await client.orders()
        except (WorkerError, Unavailable) as error:
            st.failures += 1
            st.last_error = str(error)
            return False
        st.failures, st.last_error = 0, None
        st.terminal_connected, st.terminal_trade_allowed = terminal.connected, terminal.trade_allowed
        now = self._clock.now()

        # Lifecycle facts first: the day's figures (and the enrichment below) depend on trades rebuilt from history.
        try:
            await self._track(account_id, st, client, {p.position_id: p for p in positions}, now)
        except Unavailable:
            logger.warning("position tracking for %s postponed: database unavailable", account_id)

        snapshot = client.snapshot_of(info, label=session.account.name)
        if self._enricher is not None:
            snapshot = await self._enricher(snapshot, positions)
        st.snapshot, st.positions, st.orders, st.updated_at = snapshot, positions, orders, now
        self._market.watch_also(account_id, {p.symbol for p in positions} | {o.symbol for o in orders})
        await self._events.publish(AccountSnapshotUpdated(account_id=account_id, snapshot=snapshot))
        await self._events.publish(PositionsSnapshotUpdated(account_id=account_id, positions=positions))
        return True  # the terminal was read; persistence catches up on the next cycle

    async def _track(
        self, account_id: str, st: _State, client: Mt5Client, current: dict[str, Position], now: datetime
    ) -> None:
        known_before = set(st.known)
        if not st.baselined:
            # Whatever is open when we attach is « known » — but recorded if the database has never seen it.
            already = await self._repos.positions.known_open_ids(account_id)
            for position in current.values():
                if position.position_id not in already:
                    await self._opened(account_id, position, now)
            st.known, st.by_id, st.baselined = set(current), dict(current), True
            # Rebuild the trading day from the broker: trades closed while we were not looking still count (the day's
            # trade counter and the loss streak must survive a restart). Idempotent: known facts are not republished.
            st.last_deal_scan = resolve_today_start_utc(now, client.offset) if client.offset_known else now
            await self._missed_round_trips(account_id, st, client, set(), set(current), now)
            st.last_deal_scan = now
            return

        for position_id, position in current.items():
            if position_id not in st.known:
                await self._opened(account_id, position, now)
            else:
                await self._modified(account_id, st.by_id[position_id], position)
        for position_id in st.known - set(current):
            st.pending_close.setdefault(position_id, 0)
        st.known, st.by_id = set(current), dict(current)

        await self._settle_closes(account_id, st, client)
        await self._missed_round_trips(account_id, st, client, known_before, set(current), now)
        st.last_deal_scan = now

    # ------------------------------------------------------------------------------------------ lifecycle facts
    async def _opened(self, account_id: str, position: Position, now: datetime) -> None:
        opened_at = position.opened_at or now
        if not await self._repos.positions.record_open(account_id, position.position_id, opened_at):
            return
        await self._events.publish(
            PositionOpened(
                account_id=account_id,
                position_id=position.position_id,
                symbol=position.symbol,
                side=position.side,
                volume=position.volume,
                entry_price=position.entry_price,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit,
                opened_at=opened_at,
            )
        )

    async def _modified(self, account_id: str, before: Position, after: Position) -> None:
        changes: list[tuple[Modifiable, float, float]] = [
            ("volume", before.volume, after.volume),
            ("stop_loss", before.stop_loss, after.stop_loss),
            ("take_profit", before.take_profit, after.take_profit),
        ]
        for name, previous, current in changes:
            if abs(previous - current) > 1e-9:
                await self._events.publish(
                    PositionModified(
                        account_id=account_id,
                        position_id=after.position_id,
                        field=name,
                        previous=previous,
                        current=current,
                    )
                )

    async def _settle_closes(self, account_id: str, st: _State, client: Mt5Client) -> None:
        for position_id in list(st.pending_close):
            try:
                deals = await client.deals_of_position(position_id)
            except (WorkerError, Unavailable):
                continue
            fact = closed_fact(position_id, deals, client.offset)
            if fact is None:
                st.pending_close[position_id] += 1
                if st.pending_close[position_id] >= MAX_CLOSE_ATTEMPTS:
                    logger.error(
                        "position %s closed but its deal history never completed: close not recorded", position_id
                    )
                    del st.pending_close[position_id]
                continue
            del st.pending_close[position_id]
            await self._closed(account_id, fact)

    async def _closed(self, account_id: str, fact: ClosedFact) -> None:
        trade = ClosedTrade(
            account_id=account_id,
            broker_position_id=fact.position_id,
            symbol=fact.symbol,
            side=fact.side,
            volume=fact.volume,
            realized_pnl=fact.realized_pnl,
            exit_price=fact.exit_price,
            closed_at=fact.closed_at,
        )
        if await self._repos.positions.record_closed(trade):
            await self._events.publish(PositionClosed(account_id=account_id, trade=trade))

    async def _missed_round_trips(
        self, account_id: str, st: _State, client: Mt5Client, known_before: set[str], current: set[str], now: datetime
    ) -> None:
        window = scan_window(st.last_deal_scan, now)
        if window is None:
            return
        try:
            recent = await client.deals_between(*window)
        except (WorkerError, Unavailable):
            return
        for position_id in sorted(missed_round_trip_ids(recent, known_before, current)):
            if position_id in st.pending_close:
                continue
            deals = await client.deals_of_position(position_id)
            entry = next((d for d in deals if d.entry == DEAL_ENTRY_IN), None)
            fact = closed_fact(position_id, deals, client.offset)
            if entry is None or fact is None:
                continue
            await self._opened_from_history(account_id, position_id, entry, client.offset)
            await self._closed(account_id, fact)

    async def _opened_from_history(self, account_id: str, position_id: str, entry: Deal, offset: int) -> None:
        opened = opened_fact_from_deal(position_id, entry, offset)
        if await self._repos.positions.record_open(account_id, position_id, opened.opened_at):
            await self._events.publish(
                PositionOpened(
                    account_id=account_id,
                    position_id=position_id,
                    symbol=opened.symbol,
                    side=opened.side,
                    volume=opened.volume,
                    entry_price=opened.entry_price,
                    stop_loss=0.0,
                    take_profit=0.0,
                    opened_at=opened.opened_at,
                    reconstructed=True,
                )
            )
