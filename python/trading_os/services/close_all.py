"""« Fermer toutes les positions » (ADR 0034): the human gesture that closes what is open on one account, through the path that
already exists — ``cockpit → API → ExecutionService → execution agent → MT5`` — and nothing else.

There is no second mechanism here. For each position the service builds an ordinary ``CLOSE`` request with a deterministic id
(``ca-<batch>-<positionId>``) and hands it to ``ExecutionService.submit(..., automatic=False)``: the engine persists it before
sending, replays an id it knows instead of executing twice, keeps an ambiguous outcome ``UNKNOWN`` and lets the reconciliation
settle it. A batch is therefore *its commands*; what this service adds is the preview the trader confirms, the record of what the
batch decided (an audit event, written before the first send), and the reading of the outcome (``domain/execution/close_all``).

It is a **human** gesture and says so to the engine (``automatic=False``): that is what lets it through ``HALTED``, ``OFF``,
``OBSERVE`` and ``PAPER`` (ADR 0033, 0034). The Guardian, the Position Manager and the strategies never come through here.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from trading_os.domain.accounts.models import Account, Environment
from trading_os.domain.autonomy.plan_modes import plan_mode
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.events import CloseAllRequested
from trading_os.domain.execution.agent import AgentStatus
from trading_os.domain.execution.close_all import (
    BATCH_ID_PATTERN,
    CloseAllAccount,
    CloseAllDisposition,
    CloseAllItem,
    CloseAllOrder,
    CloseAllPosition,
    CloseAllPreview,
    CloseAllReason,
    CloseAllReport,
    PlannedItem,
    assess,
    batch_prefix,
    classify,
    mask_login,
    order_command_id,
    position_command_id,
)
from trading_os.domain.execution.commands import CommandKind, ExecutionCommand, ExecutionRequest
from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.services.accounts import AccountService
from trading_os.services.execution import ExecutionService
from trading_os.services.positions import PositionService
from trading_os.services.reconciliation import ReconciliationService
from trading_os.shared.errors import Conflict, NotFound, TradingOsError, ValidationFailed
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.time import Clock

logger = logging.getLogger(__name__)

SNAPSHOT_FRESH = timedelta(seconds=15)  # the same age the readiness gives the terminal's picture
PLAN_EVENT = CloseAllRequested.wire_type


@dataclass
class _Plan:
    started_at: datetime
    include_pending_orders: bool
    items: list[PlannedItem]


def new_batch_id() -> str:
    return uuid.uuid4().hex[:12]


class CloseAllService:
    def __init__(
        self,
        *,
        accounts: AccountService,
        positions: PositionService,
        execution: ExecutionService,
        reconciliation: ReconciliationService,
        effective_mode: Callable[[Account], AutonomyMode],
        repos: Repositories,
        events: EventDispatcher,
        clock: Clock,
    ) -> None:
        self._accounts = accounts
        self._positions = positions
        self._execution = execution
        self._reconciliation = reconciliation
        self._effective_mode = effective_mode
        self._repos = repos
        self._events = events
        self._clock = clock
        self._plans: dict[tuple[str, str], _Plan] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------------------------------ the preview
    async def preview(self, account_id: str) -> CloseAllPreview:
        """What the trader is asked to confirm: the account, every open position and pending order as the broker shows them
        *now* (a fresh read of the terminal), and what would stand in the way. Sends nothing."""
        account = await self._accounts.effective(account_id)
        refreshed = await self._refresh(account_id)
        status = self._execution.agent_status(str(account.login))
        agent_magic = status.magic_number if status else None
        connected = self._accounts.session(account_id) is not None
        age = self._snapshot_age(account_id)
        fresh = refreshed and age is not None and age <= SNAPSHOT_FRESH.total_seconds()

        positions = [self._position_view(p, agent_magic) for p in self._positions.positions(account_id)]
        orders = [self._order_view(o, agent_magic) for o in self._positions.orders(account_id)]
        figures = self._positions.snapshot(account_id)
        blockers, warnings = await self._conditions(account, connected, status, orders, positions, fresh)
        mode = self._effective_mode(account)
        return CloseAllPreview(
            batch_id=new_batch_id(),
            generated_at=self._clock.now(),
            account=CloseAllAccount(
                account_id=account.id, name=account.name, provider=account.provider.value,
                environment=account.environment, login_masked=mask_login(account.login), server=account.server,
                currency=account.currency, connected=connected, mode=mode,
                plan_mode=plan_mode(mode, account.environment), agent_connected=status is not None,
                agent_magic=agent_magic, balance=figures.balance if figures else None,
                equity=figures.equity if figures else None,
            ),
            positions=positions, pending_orders=orders,
            total_unrealized_pnl=round(sum(p.unrealized_pnl for p in positions), 2),
            snapshot_age_seconds=None if age is None else round(age, 1), snapshot_fresh=fresh,
            blockers=blockers, warnings=warnings,
            can_execute=not blockers and bool(positions or orders),
        )  # fmt: skip

    async def _conditions(
        self,
        account: Account,
        connected: bool,
        status: AgentStatus | None,
        orders: list[CloseAllOrder],
        positions: list[CloseAllPosition],
        fresh: bool,
    ) -> tuple[list[CloseAllReason], list[CloseAllReason]]:
        blockers: list[CloseAllReason] = []
        warnings: list[CloseAllReason] = [
            CloseAllReason(
                code="market_price",
                detail="positions are closed at the price available when each order reaches the broker; the final result can differ from the floating figure",
            )
        ]
        if not connected:
            blockers.append(
                CloseAllReason(
                    code="account_not_connected", detail="the account is not connected: nothing can be read or sent"
                )
            )
        else:
            attached = await self._accounts.attached_account_id(account.id)
            if attached != account.id:
                blockers.append(
                    CloseAllReason(
                        code="account_mismatch",
                        detail=f"the terminal is on {attached or 'no account'}, not on {account.id}",
                    )
                )
        if status is None:
            blockers.append(
                CloseAllReason(
                    code="no_agent",
                    detail="no execution agent is connected: nothing can be sent to MT5 — close in MT5",
                )
            )
        else:
            if (refusal := status.command_refusal(exit_only=True)) is not None:
                blockers.append(CloseAllReason(code="agent_refuses", detail=refusal))
            if not status.can("close"):
                blockers.append(
                    CloseAllReason(code="agent_cannot_close", detail="the agent does not announce the close capability")
                )
            if orders and not status.can("cancel"):
                warnings.append(
                    CloseAllReason(
                        code="agent_cannot_cancel",
                        detail="the agent does not announce the cancel capability: pending orders would be refused",
                    )
                )
            if status.mode != "confirm":
                warnings.append(
                    CloseAllReason(
                        code="agent_simulates",
                        detail=f"the execution agent runs in {status.mode} mode: it validates the order and reports SIMULATED — nothing is closed at the broker",
                    )
                )
        if not fresh:
            warnings.append(
                CloseAllReason(
                    code="stale_snapshot",
                    detail="the terminal could not be read just now: the list below may be out of date",
                )
            )
        foreign = [p for p in positions if not p.closable]
        if foreign:
            warnings.append(
                CloseAllReason(
                    code="foreign_positions",
                    detail=f"{len(foreign)} position(s) were not placed by the execution agent: it will not close them — close them in MT5",
                )
            )
        if account.environment is Environment.LIVE:
            warnings.append(
                CloseAllReason(code="real_account", detail="REAL ACCOUNT — orders can cause a financial loss")
            )
        return blockers, warnings

    # ------------------------------------------------------------------------------------------ the run
    async def execute(
        self,
        account_id: str,
        *,
        batch_id: str,
        position_ids: list[str],
        include_pending_orders: bool = False,
        order_ids: list[str] | None = None,
    ) -> CloseAllReport:
        """Close exactly the positions the trader confirmed (those still open), once. Calling again with the same ``batch_id`` — a double
        click, a retry after a cut link — changes nothing that was already done: the report of the first run comes back."""
        if not BATCH_ID_PATTERN.match(batch_id):
            raise ValidationFailed("batchId must be 6 to 24 letters or digits", code="invalid_batch_id")
        account = await self._accounts.effective(account_id)  # NotFound for a stranger
        async with self._locks.setdefault(account_id, asyncio.Lock()):
            plan = await self._plan_of(account_id, batch_id)
            if plan is None:
                refreshed = await self._refresh(account_id)
                plan = await self._decide(
                    account, batch_id, position_ids, include_pending_orders, order_ids or [], refreshed
                )
            await self._send_missing(account_id, batch_id, plan)
        return await self.report(account_id, batch_id)

    async def _decide(
        self,
        account: Account,
        batch_id: str,
        position_ids: list[str],
        include_orders: bool,
        order_ids: list[str],
        refreshed: bool,
    ) -> _Plan:
        status = self._execution.agent_status(str(account.login))
        agent_magic = status.magic_number if status else None
        open_positions = {p.position_id: p for p in self._positions.positions(account.id)}
        pending = {o.order_id: o for o in self._positions.orders(account.id)}
        visible = refreshed and self._positions.baselined(account.id)
        items: list[PlannedItem] = []
        for position_id in dict.fromkeys(position_ids):
            position = open_positions.get(position_id)
            if position is None:
                items.append(_gone("position", position_id, visible))
                continue
            closable, why = _ownership(position.magic_number, agent_magic)
            items.append(
                PlannedItem(
                    target="position",
                    target_id=position_id,
                    symbol=position.symbol,
                    side=position.side,
                    volume=position.volume,
                    disposition=CloseAllDisposition.SENT if closable else CloseAllDisposition.NOT_CLOSABLE,
                    command_id=position_command_id(batch_id, position_id) if closable else None,
                    reason=why,
                )
            )
        if include_orders:
            for order_id in dict.fromkeys(order_ids):
                order = pending.get(order_id)
                if order is None:
                    items.append(_gone("order", order_id, visible))
                    continue
                closable, why = _ownership(order.magic_number, agent_magic)
                items.append(
                    PlannedItem(
                        target="order",
                        target_id=order_id,
                        symbol=order.symbol,
                        side=order.side,
                        volume=order.volume,
                        disposition=CloseAllDisposition.SENT if closable else CloseAllDisposition.NOT_CLOSABLE,
                        command_id=order_command_id(batch_id, order_id) if closable else None,
                        reason=why,
                    )
                )
        plan = _Plan(started_at=self._clock.now(), include_pending_orders=include_orders, items=items)
        self._plans[(account.id, batch_id)] = plan
        # Recorded before anything is sent: a report of this batch can always be rebuilt, even after a restart.
        await self._events.publish(
            CloseAllRequested(
                account_id=account.id, correlation_id=batch_id, batch_id=batch_id,
                include_pending_orders=include_orders, items=items,
            )
        )  # fmt: skip
        return plan

    async def _send_missing(self, account_id: str, batch_id: str, plan: _Plan) -> None:
        """Submit every decided command that has no row yet. A first run submits all of them; a retry only fills the holes — an id the
        engine knows is never submitted again."""
        for index, item in enumerate(plan.items):
            if item.disposition is not CloseAllDisposition.SENT or item.command_id is None:
                continue
            try:
                if await self._repos.execution.get(item.command_id) is not None:
                    continue
                is_position = item.target == "position"
                request = ExecutionRequest(
                    command_id=item.command_id, account_id=account_id,
                    kind=CommandKind.CLOSE if is_position else CommandKind.CANCEL, symbol=item.symbol,
                    position_id=item.target_id if is_position else None,
                    order_id=None if is_position else item.target_id, strategy_id="manual",
                )  # fmt: skip
                await self._execution.submit(request, automatic=False)
            except TradingOsError as error:
                logger.warning(
                    "close-all %s: %s %s was not submitted: %s", batch_id, item.target, item.target_id, error
                )
                plan.items[index] = item.model_copy(
                    update={
                        "disposition": CloseAllDisposition.REFUSED,
                        "reason": error.safe_message,
                        "command_id": None,
                    }
                )

    # ------------------------------------------------------------------------------------------ the report
    async def report(self, account_id: str, batch_id: str) -> CloseAllReport:
        """The batch as it stands: derived from its commands and the broker's last picture, never stored — so it is the same after a
        restart. ``COMPLETE`` only once the broker agrees *and* a reconciliation has run since the last settlement."""
        plan = await self._plan_of(account_id, batch_id)
        commands = await self._repos.execution.with_id_prefix(account_id, batch_prefix(batch_id))
        if plan is None and not commands:
            raise NotFound(f"unknown close-all batch {batch_id!r}", code="batch_not_found")
        planned = plan.items if plan else _items_from(commands)
        by_id = {c.command_id: c for c in commands}
        now = self._clock.now()
        visible = self._positions.baselined(account_id)
        open_positions = {p.position_id for p in self._positions.positions(account_id)}
        pending_orders = {o.order_id for o in self._positions.orders(account_id)}

        items: list[CloseAllItem] = []
        for item in planned:
            # a broker we cannot see confirms nothing: unseen counts as still open
            still_open = not visible or item.target_id in (
                open_positions if item.target == "position" else pending_orders
            )
            command = by_id.get(item.command_id) if item.command_id else None
            items.append(classify(item, command, still_open=still_open, now=now))

        started = plan.started_at if plan else min((c.created_at for c in commands), default=None)
        reconciled, critical = self._reconciled(account_id, commands, started)
        age = self._snapshot_age(account_id)
        in_batch = {i.target_id for i in items if i.target == "position"}
        return assess(
            batch_id=batch_id, account_id=account_id, items=items,
            include_pending_orders=plan.include_pending_orders if plan else any(i.target == "order" for i in items),
            started_at=started, now=now, reconciled=reconciled, reconciliation_critical=critical,
            snapshot_fresh=age is not None and age <= SNAPSHOT_FRESH.total_seconds() * 2,
            positions_open=len(open_positions), orders_pending=len(pending_orders),
            other_open_positions=sorted(open_positions - in_batch),
        )  # fmt: skip

    async def verify(self, account_id: str, batch_id: str) -> CloseAllReport:
        """Read the terminal now, compare the database with the broker, then report. The comparison is read-only on the broker and is
        the one place a command left ``UNKNOWN`` is settled — from the broker's own history, never by sending it again."""
        await self.report(account_id, batch_id)  # NotFound before any work for a batch nobody knows
        await self._refresh(account_id)
        with contextlib.suppress(Conflict):  # not connected: the report says what it can no longer confirm
            await self._reconciliation.reconcile(account_id)
        return await self.report(account_id, batch_id)

    # ------------------------------------------------------------------------------------------ internals
    async def _plan_of(self, account_id: str, batch_id: str) -> _Plan | None:
        known = self._plans.get((account_id, batch_id))
        if known is not None:
            return known
        try:
            rows = await self._repos.events.query(
                types=[PLAN_EVENT], account_id=account_id, correlation_id=batch_id, limit=1
            )
        except TradingOsError:
            return None
        if not rows:
            return None
        payload = rows[0]["payload"]
        plan = _Plan(
            started_at=rows[0]["occurred_at"], include_pending_orders=bool(payload.get("includePendingOrders")),
            items=[PlannedItem.model_validate(i) for i in payload.get("items", [])],
        )  # fmt: skip
        self._plans[(account_id, batch_id)] = plan
        return plan

    async def _refresh(self, account_id: str) -> bool:
        """A fresh read of the terminal. False when it could not be read — the last picture is then all there is."""
        if self._accounts.session(account_id) is None:
            return False
        try:
            return await self._positions.poll(account_id)
        except TradingOsError:
            return False

    def _snapshot_age(self, account_id: str) -> float | None:
        updated = self._positions.updated_at(account_id)
        return None if updated is None else (self._clock.now() - updated).total_seconds()

    def _reconciled(
        self, account_id: str, commands: list[ExecutionCommand], started: datetime | None
    ) -> tuple[bool, int]:
        last = self._reconciliation.last_success_at(account_id)
        readable = self._reconciliation.last_readable_report(account_id)
        critical = len(readable.critical) if readable else 0
        settled = [c.completed_at or c.created_at for c in commands]
        reference = max(settled) if settled else started
        return last is not None and reference is not None and last > reference and critical == 0, critical

    @staticmethod
    def _position_view(position: Position, agent_magic: int | None) -> CloseAllPosition:
        closable, why = _ownership(position.magic_number, agent_magic)
        return CloseAllPosition(
            position_id=position.position_id, symbol=position.symbol, side=position.side, volume=position.volume,
            entry_price=position.entry_price, current_price=position.current_price, stop_loss=position.stop_loss,
            take_profit=position.take_profit, unrealized_pnl=position.unrealized_pnl, strategy_id=position.strategy_id,
            closable=closable, not_closable_reason=why,
        )  # fmt: skip

    @staticmethod
    def _order_view(order: PendingOrder, agent_magic: int | None) -> CloseAllOrder:
        cancellable, why = _ownership(order.magic_number, agent_magic)
        return CloseAllOrder(
            order_id=order.order_id, symbol=order.symbol, side=order.side, order_type=order.order_type,
            volume=order.volume, price=order.price, cancellable=cancellable, not_cancellable_reason=why,
        )  # fmt: skip


def _gone(target: str, target_id: str, visible: bool) -> PlannedItem:
    """A confirmed target that the broker no longer shows. Only a terminal that was just read can say it is closed; otherwise it is
    an unverified target the trader must look at in MT5."""
    kind = "position" if target == "position" else "order"
    if visible:
        return PlannedItem(
            target=kind, target_id=target_id, symbol="?", disposition=CloseAllDisposition.ALREADY_CLOSED,
            reason="not open at the broker when the order came to be sent",
        )  # fmt: skip
    return PlannedItem(
        target=kind, target_id=target_id, symbol="?", disposition=CloseAllDisposition.NOT_CLOSABLE,
        reason="the terminal could not be read: this target could not be verified — check it in MT5",
    )  # fmt: skip


def _ownership(magic: int | None, agent_magic: int | None) -> tuple[bool, str | None]:
    """The execution agent closes and cancels only what carries its own magic number (TARGET_NOT_OURS, ADR 0010/0029). Unknown on
    either side is not a refusal here: the agent's own barrier still decides."""
    if magic is None or agent_magic is None or magic == agent_magic:
        return True, None
    return False, f"magic number {magic} is not the execution agent's ({agent_magic}): it closes only what it placed"


def _items_from(commands: list[ExecutionCommand]) -> list[PlannedItem]:
    """A batch whose audit event is gone: rebuilt from its commands alone."""
    items = []
    for command in commands:
        request = command.request
        is_order = request.kind is CommandKind.CANCEL
        items.append(
            PlannedItem(
                target="order" if is_order else "position",
                target_id=(request.order_id if is_order else request.position_id) or command.command_id,
                symbol=request.symbol,
                side=request.side,
                volume=request.volume,
                disposition=CloseAllDisposition.SENT,
                command_id=command.command_id,
            )
        )
    return items
