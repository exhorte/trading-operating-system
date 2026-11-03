"""Reconciliation: the Trading OS's picture of an account, compared with what the broker shows (mission § 21).

One run per connected account, every few seconds (the scheduler drives it, the supervisor can force one):

1. **Read the broker first** — which account the terminal is really logged into, open positions, pending orders. The order
   matters: a position can only exist after its command row does (the row is written before anything is sent), so reading
   MT5 *then* the database guarantees every position seen has its command in the snapshot. The reverse order would call
   a brand-new fill « unexpected ».
2. **Settle what is in doubt.** A command left UNKNOWN / RECONCILING is searched for in the broker's own data — open
   positions, opening deals, pending orders, refused orders — by magic number and the comment trace the agent writes
   (``domain/execution/resolution.py``), and moves through ``ExecutionService.settle``: the same door the execution
   agent's own answer uses. « Not found » closes nothing; it is retried with a back-off.
3. **Compare** (pure, ``domain/positions/reconciliation.py``): what the executed commands should have left at the broker
   against what is there — missing, unexpected, wrong volume / stop / target, and positions that contradict the record.
4. **Confirm** executed commands whose position is really there (EXECUTED → RECONCILED).
5. **Publish** each *new or escalated* finding once — not every run — plus a summary the supervisor reads.

Everything here is read-only towards the broker. The service never places, modifies or closes anything; it only observes
and records. A run that cannot read MT5 or the database concludes nothing (``readable=False``) and counts as a failure the
supervisor can escalate — it never reports a clean state it did not verify.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from trading_os.domain.events import (
    ReconciliationCompleted,
    ReconciliationMismatch,
    ReconciliationStarted,
)
from trading_os.domain.execution.agent import AgentStatus
from trading_os.domain.execution.commands import CommandKind, CommandState, ExecutionCommand
from trading_os.domain.execution.records import PositionScanRecord, ReconciliationRecord
from trading_os.domain.execution.resolution import BrokerEvidence, BrokerFill, BrokerOrderRecord, resolve_command
from trading_os.domain.execution.trace import command_trace
from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.domain.positions.reconciliation import (
    ExpectedPosition,
    Mismatch,
    MismatchSeverity,
    ReconciliationInput,
    ReconciliationReport,
    UnresolvedCommand,
    reconcile,
)
from trading_os.domain.primitives import Side
from trading_os.domain.strategy.intent import OrderKind
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.infrastructure.mt5.client import ORDER_SIDES, Mt5Client
from trading_os.infrastructure.mt5.mt5_semantics import DEAL_ENTRY_IN, DEAL_ENTRY_OUT, Deal, HistoryOrder, side_of_deal
from trading_os.infrastructure.mt5.protocol import WorkerError
from trading_os.infrastructure.mt5.wire import side_to_wire
from trading_os.services.accounts import AccountService
from trading_os.services.execution import ExecutionService
from trading_os.shared.errors import Conflict, TradingOsError, Unavailable
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)

LOOKBACK = timedelta(days=30)  # commands considered: far longer than any position this workstation holds
HISTORY_WINDOW = timedelta(days=7)  # broker history read when evidence is needed (wider if a command is older)
HISTORY_PAD = timedelta(hours=6)  # the broker's clock may not be measured yet: never trust a tight window
GRACE = timedelta(seconds=30)  # a fill reaches the position list and the history a moment after the report
RETRY_FIRST = timedelta(seconds=10)  # « not found » is searched again after this, then twice as long each time …
RETRY_MAX = timedelta(minutes=5)  # … up to this


@dataclass
class _Broker:
    """What this run read from the terminal. History is read once, lazily, and only when something needs it."""

    client: Mt5Client
    positions: list[Position]
    orders: list[PendingOrder]
    now: datetime
    _deals: list[Deal] | None = None
    _history_orders: list[HistoryOrder] | None = None
    _since: datetime | None = None

    async def _load(self, since: datetime) -> None:
        wanted = min(since - HISTORY_PAD, self.now - HISTORY_WINDOW)
        if self._deals is not None and self._since is not None and self._since <= wanted:
            return
        end = self.now + HISTORY_PAD
        self._deals = await self.client.deals_between(wanted, end)
        self._history_orders = await self.client.history_orders_between(wanted, end)
        self._since = wanted

    async def deals(self, since: datetime) -> list[Deal]:
        await self._load(since)
        assert self._deals is not None
        return self._deals

    async def evidence(self, since: datetime, our_magic: int | None) -> BrokerEvidence:
        deals = await self.deals(since)
        history = self._history_orders or []
        return BrokerEvidence(
            positions=self.positions,
            pending_orders=self.orders,
            entry_deals=[
                BrokerFill(
                    position_id=str(d.position_id),
                    order_id=str(d.order or d.ticket),
                    symbol=d.symbol,
                    side=side_of_deal(d),
                    volume=d.volume,
                    price=d.price,
                    magic=d.magic,
                    comment=d.comment,
                )
                for d in deals
                if d.entry == DEAL_ENTRY_IN
            ],
            history_orders=[
                BrokerOrderRecord(
                    order_id=str(o.ticket),
                    symbol=o.symbol,
                    side=ORDER_SIDES.get(o.type, Side.BUY),
                    filled=o.filled,
                    state=_order_state_name(o.state),
                    magic=o.magic,
                    comment=o.comment,
                )
                for o in history
            ],
            our_magic=our_magic,
        )


_ORDER_STATES = {0: "STARTED", 1: "PLACED", 2: "CANCELED", 3: "PARTIAL", 4: "FILLED", 5: "REJECTED", 6: "EXPIRED"}


def _order_state_name(state: int) -> str:
    return _ORDER_STATES.get(state, f"STATE_{state}")


def _has_filled(command: ExecutionCommand) -> bool:
    """A command that left (or should have left) a position at the broker."""
    if command.request.kind is not CommandKind.OPEN or command.request.side is None:
        return False
    if command.state is CommandState.EXECUTED:
        return True
    return command.state is CommandState.RECONCILED and bool(
        command.broker_position_id or (command.filled_volume or 0) > 0
    )


class ReconciliationService:
    def __init__(
        self,
        *,
        accounts: AccountService,
        execution: ExecutionService,
        repos: Repositories,
        events: EventDispatcher,
        clock: Clock,
        lookback: timedelta = LOOKBACK,
    ) -> None:
        self._accounts = accounts
        self._execution = execution
        self._repos = repos
        self._events = events
        self._clock = clock
        self._lookback = lookback
        self._reports: dict[str, ReconciliationReport] = {}
        self._readable: dict[str, ReconciliationReport] = {}  # the last run that actually read its inputs
        self._standing: dict[str, dict[str, Mismatch]] = {}  # account → finding key → finding still present
        self._failures: dict[str, int] = {}
        self._last_success: dict[str, datetime] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._attempts: dict[str, tuple[datetime, int]] = {}  # command id → (last search, searches so far)
        self._magic: dict[str, int] = {}

    # ------------------------------------------------------------------------------------------ reading
    def report(self, account_id: str) -> ReconciliationReport | None:
        return self._reports.get(account_id)

    def last_readable_report(self, account_id: str) -> ReconciliationReport | None:
        """The last run that read its inputs. A run that could not read concludes nothing — in particular it does not
        clear what an earlier run found: a divergence nobody can re-check is not a divergence that went away."""
        return self._readable.get(account_id)

    def consecutive_failures(self, account_id: str) -> int:
        """Runs in a row that could not read MT5 or the database (0 after any readable run)."""
        return self._failures.get(account_id, 0)

    def last_success_at(self, account_id: str) -> datetime | None:
        return self._last_success.get(account_id)

    def forget(self, account_id: str) -> None:
        """The account was disconnected: what was found about it is no longer current."""
        for table in (self._reports, self._readable, self._standing, self._failures, self._last_success):
            table.pop(account_id, None)

    # ------------------------------------------------------------------------------------------ running
    async def reconcile_connected(self) -> list[ReconciliationReport]:
        return [await self.reconcile(account_id) for account_id in self._accounts.connected_ids()]

    async def reconcile(self, account_id: str) -> ReconciliationReport:
        if self._accounts.session(account_id) is None:
            raise Conflict("connect the account before reconciling it", code="account_not_connected")
        async with self._locks.setdefault(account_id, asyncio.Lock()):
            started = self._clock.now()
            await self._events.publish(ReconciliationStarted(account_id=account_id))
            try:
                report = await self._run(account_id, started)
            except (WorkerError, Unavailable) as error:
                self._failures[account_id] = self._failures.get(account_id, 0) + 1
                message = error.safe_message if isinstance(error, TradingOsError) else str(error)
                logger.warning("reconciliation of %s could not read its inputs: %s", account_id, message)
                report = ReconciliationReport(
                    account_id=account_id, started_at=started, finished_at=self._clock.now(), readable=False,
                    error=message,
                )  # fmt: skip
            else:
                self._failures[account_id] = 0
                self._last_success[account_id] = report.finished_at
            self._reports[account_id] = report
            if report.readable:
                self._readable[account_id] = report
            await self._events.publish(
                ReconciliationCompleted(
                    account_id=account_id, mismatches=len(report.mismatches), critical=len(report.critical),
                    positions_checked=report.positions_checked, readable=report.readable,
                )
            )  # fmt: skip
            return report

    async def _run(self, account_id: str, started: datetime) -> ReconciliationReport:
        session = self._accounts.session(account_id)
        if session is None:
            raise Unavailable("the account was disconnected during the run", code="account_not_connected")
        account, client = session.account, session.client

        # 1. the broker first (see the module docstring for why the order matters)
        attached = await self._accounts.attached_account_id(account_id)
        if attached is None:  # no answer is not « another account »: the terminal could not be read
            raise Unavailable("the terminal could not be read", code="mt5_unreadable")
        if attached != account_id:
            found = reconcile(ReconciliationInput(account_id=account_id, now=started, connected_account_id=attached))
            await self._publish_changes(account_id, found)
            return ReconciliationReport(
                account_id=account_id, started_at=started, finished_at=self._clock.now(), readable=True,
                mismatches=found,
            )  # fmt: skip
        broker = _Broker(client, await client.positions(), await client.orders(), self._clock.now())

        # 2. the database, then what is in doubt
        commands = await self._repos.execution.created_since(account_id, broker.now - self._lookback)
        scans = await self._repos.positions.scans(account_id)
        magic = self._our_magic(account_id, self._execution.agent_status(str(account.login)), scans)
        settled = await self._settle_in_doubt(account_id, commands, broker, magic)
        if settled:
            commands = await self._repos.execution.created_since(account_id, broker.now - self._lookback)

        # 3. compare
        expected, closed = await self._expected(account_id, commands, broker, magic)
        found = reconcile(
            ReconciliationInput(
                account_id=account_id,
                now=broker.now,
                connected_account_id=attached,
                expected=expected,
                actual=broker.positions,
                command_by_position={s.broker_position_id: s.known_command_id for s in scans if s.known_command_id},
                command_states={c.command_id: c.state for c in commands},
                closed_position_ids=frozenset(closed),
                our_magic=magic,
                unresolved=[
                    UnresolvedCommand(command_id=c.command_id, state=c.state, since=c.sent_at or c.created_at)
                    for c in commands
                    if c.state in (CommandState.UNKNOWN, CommandState.RECONCILING)
                ],
                actual_orders=broker.orders,
                grace=GRACE,
            )
        )

        # 4. confirm what is verifiably there
        confirmed = await self._confirm(commands, expected, found, {p.position_id for p in broker.positions}, closed)

        # 5. publish what changed
        await self._publish_changes(account_id, found)
        return ReconciliationReport(
            account_id=account_id, started_at=started, finished_at=self._clock.now(), readable=True,
            positions_checked=len(broker.positions), settled=settled, confirmed=confirmed, mismatches=found,
        )  # fmt: skip

    # ------------------------------------------------------------------------------------------ the agent's magic number
    def _our_magic(self, account_id: str, status: AgentStatus | None, scans: list[PositionScanRecord]) -> int | None:
        """The number every order of the execution agent is stamped with: from its id while it is connected, else
        remembered, else from the positions it once scanned as its own."""
        if status is not None and status.magic_number is not None:
            self._magic[account_id] = status.magic_number
        elif account_id not in self._magic:
            own = next((s.magic_number for s in scans if not s.is_external), None)
            if own is not None:
                self._magic[account_id] = own
        return self._magic.get(account_id)

    # ------------------------------------------------------------------------------------------ in doubt
    def _due(self, command_id: str, now: datetime) -> bool:
        previous = self._attempts.get(command_id)
        if previous is None:
            return True
        when, searches = previous
        return now - when >= min(RETRY_FIRST * (1 << max(searches - 1, 0)), RETRY_MAX)

    async def _settle_in_doubt(
        self, account_id: str, commands: list[ExecutionCommand], broker: _Broker, magic: int | None
    ) -> int:
        doubtful = [
            c for c in commands if c.state in (CommandState.UNKNOWN, CommandState.RECONCILING)
            and self._due(c.command_id, broker.now)
        ]  # fmt: skip
        if not doubtful:
            return 0
        evidence = await broker.evidence(min(c.created_at for c in doubtful), magic)
        settled = 0
        for command in doubtful:
            resolution = resolve_command(command.command_id, evidence)
            record = ReconciliationRecord(
                command_id=command.command_id, account_id=account_id, outcome=resolution.outcome,
                symbol=resolution.symbol, side=side_to_wire(resolution.side) if resolution.side else None,
                broker_order_id=resolution.broker_order_id, broker_position_id=resolution.broker_position_id,
                filled_volume=resolution.filled_volume, average_price=resolution.average_price,
                attempts=command.attempts + 1, detail=resolution.detail, reconciled_at=broker.now,
            )  # fmt: skip
            updated = await self._execution.settle(record, source="core")
            if resolution.outcome == "not_found":
                searches = self._attempts.get(command.command_id, (broker.now, 0))[1] + 1
                self._attempts[command.command_id] = (broker.now, searches)
            else:
                self._attempts.pop(command.command_id, None)
                if updated is not None and updated.state is CommandState.RECONCILED:
                    settled += 1
                    logger.info("command %s settled from the broker's data: %s", command.command_id, resolution.detail)
        return settled

    # ------------------------------------------------------------------------------------------ expectations
    async def _expected(
        self, account_id: str, commands: list[ExecutionCommand], broker: _Broker, magic: int | None
    ) -> tuple[list[ExpectedPosition], set[str]]:
        """The positions executed commands should have left, and which of those are known to be closed already."""
        filled = [c for c in commands if _has_filled(c)]
        if not filled:
            return [], set()
        when = await self._repos.execution.executed_at([c.command_id for c in filled])
        live = {p.position_id: p for p in broker.positions}
        by_trace = {p.comment: p.position_id for p in broker.positions}

        def position_of(command: ExecutionCommand) -> str | None:
            return command.broker_position_id or by_trace.get(command_trace(command.command_id))

        named = [pid for c in filled if (pid := position_of(c)) is not None]
        closed = await self._repos.positions.closed_ids(account_id, named)

        expected: list[ExpectedPosition] = []
        for command in filled:
            executed_at = when.get(command.command_id) or command.completed_at or command.created_at
            position_id = position_of(command)
            if command.request.order_type is OrderKind.LIMIT and position_id is None:
                # A LIMIT order the broker accepted (EXECUTED) rests until the market reaches it: no position yet is the normal
                # state, not a missing one. It is compared with its position once one carries the command's trace (ADR 0029).
                continue
            lost = (position_id is None or position_id not in live) and position_id not in closed
            if lost and broker.now - executed_at >= GRACE:
                # Not open, not recorded closed: the history says whether it closed (stop, target, by hand) or is gone.
                position_id = await self._look_in_history(command, position_id, executed_at, broker, magic, closed)
            request = command.request
            volume = command.filled_volume or request.volume
            if request.side is None or not volume:
                continue
            expected.append(
                ExpectedPosition(
                    command_id=command.command_id, account_id=account_id, symbol=request.symbol, side=request.side,
                    volume=volume, stop_loss=request.stop_loss or 0.0, take_profit=request.take_profit or 0.0,
                    broker_position_id=position_id, executed_at=executed_at,
                )
            )  # fmt: skip
        return expected, closed

    async def _look_in_history(
        self,
        command: ExecutionCommand,
        position_id: str | None,
        executed_at: datetime,
        broker: _Broker,
        magic: int | None,
        closed: set[str],
    ) -> str | None:
        """Find out in the deal history whether a position that is not open has closed. Adds it to ``closed`` if so and
        returns the position id the history names (the one the fill report never carried, if that was the case)."""
        deals = await broker.deals(command.created_at)
        if position_id is None:
            evidence = await broker.evidence(command.created_at, magic)
            found = resolve_command(command.command_id, evidence)
            position_id = found.broker_position_id
        if position_id is not None and any(
            str(d.position_id) == position_id and d.entry == DEAL_ENTRY_OUT for d in deals
        ):
            closed.add(position_id)
        return position_id

    # ------------------------------------------------------------------------------------------ confirmation
    async def _confirm(
        self,
        commands: list[ExecutionCommand],
        expected: list[ExpectedPosition],
        found: list[Mismatch],
        live_ids: set[str],
        closed: set[str],
    ) -> int:
        """EXECUTED → RECONCILED for commands whose position is there (or has verifiably been there and closed) with no
        critical divergence. A warning — a stop the user moved — does not hide that the position exists."""
        critical = {m.command_id for m in found if m.severity is MismatchSeverity.CRITICAL and m.command_id}
        states = {c.command_id: c.state for c in commands}
        confirmed = 0
        for exp in expected:
            if states.get(exp.command_id) is not CommandState.EXECUTED or exp.command_id in critical:
                continue
            position_id = exp.broker_position_id
            if position_id is None or (position_id not in live_ids and position_id not in closed):
                continue  # nothing verifiable yet: still inside the grace period, or reported as missing above
            if await self._execution.confirm_position(exp.command_id) is not None:
                confirmed += 1
        return confirmed

    # ------------------------------------------------------------------------------------------ publication
    async def _publish_changes(self, account_id: str, found: list[Mismatch]) -> None:
        """Each finding is announced once, when it first appears or gets worse; a finding that persists is not re-sent
        every run (it would drown the audit trail), and one that disappears is simply gone from the next report."""
        previous = self._standing.get(account_id, {})
        current = {m.key: m for m in found}
        for key, mismatch in current.items():
            before = previous.get(key)
            if before is not None and before.severity is mismatch.severity:
                continue
            level = logging.ERROR if mismatch.severity is MismatchSeverity.CRITICAL else logging.WARNING
            logger.log(level, "reconciliation %s on %s: %s", mismatch.kind.value, account_id, mismatch.detail)
            await self._events.publish(
                ReconciliationMismatch(account_id=account_id, correlation_id=mismatch.command_id, mismatch=mismatch)
            )
        for key in previous.keys() - current.keys():
            logger.info("reconciliation finding cleared on %s: %s", account_id, previous[key].detail)
        self._standing[account_id] = current


__all__ = ["ReconciliationService"]
