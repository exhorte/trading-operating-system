"""The journal: every trade, from the intention to the outcome — written by the events themselves, never by hand (T05–T07).

* **Captures (T05).** On ``PositionOpened`` and ``PositionClosed`` the service writes the immutable capture rows: the entry
  price, stop and target as they were when the position opened, and the exit price when it closed. Numbers, never an image
  and no chart window — the graphic capture was removed (ADR 0018); the data stayed. A trade whose entry row is missing gets
  no exit row: an open nobody saw is not invented.
* **Trades (T06).** A read view over what the other services already persist (closed trades, opens, captures) — no table of
  its own, so there is nothing to drift from the facts. Each trade carries the R it returned and the rules it broke.
* **Compliance (T07).** Judged here, once, by the pure detectors of ``domain/journal/compliance`` — against the account's
  *current* effective rules and balance, an approximation the rules ledger could refine later (there is no historical
  balance table).
* **The file of a trade.** Intent → risk decision → command → position → outcome, followed through the persisted links; a
  position nobody commanded says so.

Reading works with the terminal off: it only needs the database. The size check, which needs the broker's symbol
specification and the balance, is simply skipped when the account is not connected.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from trading_os.domain.accounts.models import Account
from trading_os.domain.events import PositionClosed, PositionOpened
from trading_os.domain.journal.compliance import evaluate_trade, r_multiple, summarize_compliance
from trading_os.domain.journal.models import (
    ComplianceSummary,
    JournalTrade,
    JournalTradeView,
    TradeCapture,
    TradeFile,
)
from trading_os.domain.market.models import SymbolSpec
from trading_os.domain.market.sessions import session_for_timestamp
from trading_os.domain.risk.lockout import LockoutWindow
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.services.accounts import AccountService
from trading_os.services.market_data import MarketDataService
from trading_os.services.positions import PositionService
from trading_os.shared.errors import NotFound, Unavailable
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Context:
    """What the judging needs, read once per request."""

    account: Account
    lockouts: list[LockoutWindow]
    balance: float | None  # the account's current balance: None while it is not connected
    specs: dict[str, SymbolSpec]


class JournalService:
    def __init__(
        self,
        *,
        repos: Repositories,
        events: EventDispatcher,
        clock: Clock,
        accounts: AccountService,
        positions: PositionService,
        market: MarketDataService,
    ) -> None:
        self._repos = repos
        self._events = events
        self._clock = clock
        self._accounts = accounts
        self._positions = positions
        self._market = market

    # ------------------------------------------------------------------------------------------ the events write the facts
    def subscribe(self) -> None:
        self._events.subscribe(PositionOpened, self._on_opened)
        self._events.subscribe(PositionClosed, self._on_closed)

    async def _on_opened(self, event: PositionOpened) -> None:
        if event.account_id is None:
            return
        try:
            await self._repos.positions.record_capture_entry(
                event.account_id, event.position_id, event.symbol, event.opened_at,
                event.entry_price, event.stop_loss, event.take_profit,
            )  # fmt: skip
        except Unavailable:
            logger.warning("entry capture of %s not recorded: database unavailable", event.position_id)

    async def _on_closed(self, event: PositionClosed) -> None:
        trade = event.trade
        try:
            recorded = await self._repos.positions.record_capture_exit(
                trade.account_id, trade.broker_position_id, trade.exit_price, trade.closed_at
            )
        except Unavailable:
            logger.warning("exit capture of %s not recorded: database unavailable", trade.broker_position_id)
            return
        if not recorded:
            logger.info(
                "no exit capture for %s: its entry was never captured (or it already has one)", trade.broker_position_id
            )

    # ------------------------------------------------------------------------------------------ trades and compliance
    async def trades(self, account_id: str, start: datetime, end: datetime) -> list[JournalTradeView]:
        """Closed trades in the window, newest first, each with its R multiple and the rules it broke."""
        trades = await self._repos.positions.journal_trades(account_id, start, end)
        context = await self._context(account_id, end)
        return [self._view(trade, context) for trade in trades]

    async def compliance(self, account_id: str, start: datetime, end: datetime) -> ComplianceSummary:
        trades = await self._repos.positions.journal_trades(account_id, start, end)
        context = await self._context(account_id, end)
        return summarize_compliance(
            trades, context.lockouts, context.account.trading_rules.trading_windows,
            balance=context.balance, max_risk_percent=context.account.risk_profile.max_risk_per_trade_percent,
            specs=context.specs,
        )  # fmt: skip

    async def lockouts(self, account_id: str, up_to: datetime) -> list[LockoutWindow]:
        """The lockout ledger as recorded, active or not (what compliance replays against the trades)."""
        return await self._repos.risk.lockout_history(account_id, up_to)

    async def captures(
        self, account_id: str, broker_position_id: str
    ) -> tuple[TradeCapture | None, TradeCapture | None]:
        return await self._repos.positions.captures(account_id, broker_position_id)

    # ------------------------------------------------------------------------------------------ one trade, whole
    async def trade_file(self, account_id: str, broker_position_id: str) -> TradeFile:
        """The reconstruction of one position. ``NotFound`` when the core has never heard of it."""
        entry, exit_ = await self._repos.positions.captures(account_id, broker_position_id)
        command = await self._repos.execution.for_position(account_id, broker_position_id)
        closed = await self._repos.positions.journal_trade(account_id, broker_position_id)
        if entry is None and exit_ is None and command is None and closed is None:
            raise NotFound(f"no trace of position {broker_position_id}", code="position_not_found")
        decision = None
        intent = None
        if command is not None and command.request.risk_decision_id:
            decision = await self._repos.risk.get_decision(command.request.risk_decision_id)
            if decision is not None and decision.intent_id:
                intent = await self._repos.strategy.get_intent(decision.intent_id)
        violations = []
        r = None
        if closed is not None:
            context = await self._context(account_id, closed.closed_at)
            view = self._view(closed, context)
            violations, r = view.violations, view.r_multiple
        return TradeFile(
            account_id=account_id, broker_position_id=broker_position_id, status="closed" if closed else "open",
            manual=command is None, trade=closed, entry_capture=entry, exit_capture=exit_, command=command,
            decision=decision, intent=intent, r_multiple=r, violations=violations,
        )  # fmt: skip

    # ------------------------------------------------------------------------------------------ the judging context
    async def _context(self, account_id: str, up_to: datetime) -> _Context:
        account = await self._accounts.effective(account_id)
        snapshot = self._positions.snapshot(account_id)
        return _Context(
            account=account,
            lockouts=await self._repos.risk.lockout_history(account_id, up_to),
            balance=snapshot.balance if snapshot is not None else None,
            specs=self._market.specs(account_id),
        )

    @staticmethod
    def _view(trade: JournalTrade, context: _Context) -> JournalTradeView:
        violations = evaluate_trade(
            trade, context.lockouts, context.account.trading_rules.trading_windows,
            balance=context.balance, max_risk_percent=context.account.risk_profile.max_risk_per_trade_percent,
            spec=context.specs.get(trade.symbol),
        )  # fmt: skip
        session = session_for_timestamp(trade.opened_at) if trade.opened_at is not None else None
        return JournalTradeView(
            **trade.model_dump(), r_multiple=r_multiple(trade), violations=violations, session=session
        )
