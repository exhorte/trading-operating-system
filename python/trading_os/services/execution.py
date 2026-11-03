"""The execution engine: the centralised path from an approved decision to (at most) one order.

    ExecutionRequest ─▶ replay? ─▶ validation ─▶ **persist PENDING** ─▶ route ─▶ sender ─▶ ack / report ─▶ final state

Guarantees held here (each has a test):

* **one commandId, at most one execution.** The id is the idempotency key: same id and same content returns the recorded
  command; same id with different content is refused. The row exists *before* anything is sent.
* **no order without the Risk Engine.** An OPEN command needs a persisted, approved, unexpired decision for this account,
  and may not exceed what it approved (symbol, side, volume, stop).
* **the account is checked live.** The command's ``accountId`` must be the account the terminal is really logged into.
* **fail closed.** If the command cannot be persisted nothing is sent (``STORE_UNAVAILABLE``).
* **UNKNOWN is first-class.** A silence after the send, a lost link, an ambiguous broker return code (10011/10012/10031 or
  none) leave the command UNKNOWN — never FAILED, never replayed. Only reconciliation closes it.
* **OBSERVE sends nothing.** The route comes from the autonomy mode; OBSERVE and OFF go to a sender that cannot send.

The agent's replies reach this service through the ``EaLinkHandler`` methods below; the transitions all go through
``domain/execution/state.py`` and are applied as compare-and-set on the stored state.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Literal, Protocol

from pydantic import Field

from trading_os.domain.accounts.models import Account
from trading_os.domain.autonomy.state import AutonomyMode, ExecutionRoute, route_for
from trading_os.domain.events import (
    AgentConnected,
    AgentDisconnected,
    AgentHeartbeatReceived,
    AgentStatusChanged,
    CommandReconciled,
    ExecutionAcknowledged,
    ExecutionCommandCreated,
    ExecutionCommandSent,
    ExecutionFailed,
    ExecutionRejected,
    ExecutionReported,
    ExecutionUnknown,
)
from trading_os.domain.execution.agent import AgentStatus
from trading_os.domain.execution.commands import CommandState, ExecutionCommand, ExecutionRequest
from trading_os.domain.execution.idempotency import ReplayOutcome, check_replay, request_fingerprint
from trading_os.domain.execution.reasons import RejectCode, Rejection
from trading_os.domain.execution.records import (
    AckRecord,
    PositionScanRecord,
    ReconciliationRecord,
    ReportRecord,
)
from trading_os.domain.execution.retcodes import RetcodeClass, classify_failed_report
from trading_os.domain.execution.state import CommandEvent, is_terminal, next_state
from trading_os.domain.execution.validation import LIMIT_CAPABILITY, ValidationContext, validate
from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.domain.primitives import DomainModel
from trading_os.infrastructure.database.repositories import Repositories
from trading_os.infrastructure.mt5.wire import (
    SUCCESS_REPORT_STATUSES,
    AgentHeartbeat,
    ExecutionAck,
    ExecutionReconciled,
    ExecutionReport,
    PositionScan,
    side_from_wire,
)
from trading_os.services.accounts import AccountService
from trading_os.services.senders import OrderSender, SendResult
from trading_os.shared.errors import Conflict, IllegalTransition, NotFound, Unavailable
from trading_os.shared.events.dispatcher import EventDispatcher
from trading_os.shared.time import Clock, from_epoch_ms

logger = logging.getLogger(__name__)

ACK_TIMEOUT = timedelta(seconds=15)  # sent, no acknowledgement: the outcome is not known
REPORT_TIMEOUT = timedelta(seconds=90)  # acknowledged, no final report


class AgentLinkPort(Protocol):
    def status(self, login: str) -> AgentStatus | None: ...
    def is_connected(self, login: str | None = None) -> bool: ...
    async def send_halt(self, login: str, reason: str) -> bool: ...
    def registered_logins(self) -> list[str]: ...


class PositionView(Protocol):
    """What the engine reads of the broker's exposure to check a management command (ADR 0023)."""

    def positions(self, account_id: str) -> list[Position]: ...
    def orders(self, account_id: str) -> list[PendingOrder]: ...
    def baselined(self, account_id: str) -> bool: ...


class ExecutionOutcome(DomainModel):
    command: ExecutionCommand
    replayed: bool = False
    rejections: list[Rejection] = Field(default_factory=list)
    awaiting_confirmation: bool = False


class ExecutionService:
    def __init__(
        self,
        *,
        accounts: AccountService,
        repos: Repositories,
        events: EventDispatcher,
        clock: Clock,
        link: AgentLinkPort,
        senders: dict[ExecutionRoute, OrderSender],
        effective_mode: Callable[[Account], AutonomyMode],
        halted: Callable[[], bool] = lambda: False,
        positions: PositionView | None = None,
    ) -> None:
        self._positions = positions
        self._accounts = accounts
        self._repos = repos
        self._events = events
        self._clock = clock
        self._link = link
        self._senders = senders
        self._effective_mode = effective_mode
        self._halted = halted
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_beat: dict[str, datetime] = {}
        self._login_to_account: dict[str, str] = {}
        self.last_error: str | None = None

    # ------------------------------------------------------------------------------------------ agent view
    def agent_status(self, login: str) -> AgentStatus | None:
        return self._link.status(login)

    def last_heartbeat(self, login: str) -> datetime | None:
        return self._last_beat.get(login)

    async def _account_for_login(self, login: str) -> str | None:
        known = self._login_to_account.get(login)
        if known is not None:
            return known
        for account in await self._repos.accounts.all():
            self._login_to_account[str(account.login)] = account.id
        return self._login_to_account.get(login)

    async def guard(self, account_id: str) -> str | None:
        """For ``AccountService``: an order that may exist at the broker blocks disconnecting or switching away."""
        try:
            doubtful = await self._repos.execution.in_doubt(account_id)
        except Unavailable:
            return "cannot check for commands in doubt: database unavailable"
        return f"{len(doubtful)} command(s) sent and not yet settled" if doubtful else None

    # ------------------------------------------------------------------------------------------ submission
    async def submit(self, request: ExecutionRequest, *, automatic: bool = False) -> ExecutionOutcome:
        """Create (or replay) a command. ``automatic`` = issued by the strategy pipeline; otherwise a human gesture,
        which is itself the confirmation CONFIRM mode waits for."""
        now = self._clock.now()
        existing = await self._repos.execution.get(request.command_id)
        replay = check_replay(existing, request)
        if replay.outcome is ReplayOutcome.REPLAY and replay.existing is not None:
            return ExecutionOutcome(command=replay.existing, replayed=True)
        if replay.outcome is ReplayOutcome.CONFLICT:
            raise Conflict(
                f"commandId {request.command_id!r} was already used for a different order",
                code=RejectCode.DUPLICATE_CONFLICT.value,
            )

        account = await self._accounts.effective(request.account_id) if await self._known(request.account_id) else None
        mode = self._effective_mode(account) if account else AutonomyMode.OFF
        route = self._route_for(mode, request, automatic=automatic)
        problems = await self._validate(request, account, route, automatic=automatic, now=now)
        ttl = (
            timedelta(seconds=account.execution_profile.limits.command_ttl_seconds)
            if account
            else timedelta(seconds=60)
        )
        expires_at = request.expires_at or now + ttl
        stored = request.model_copy(update={"expires_at": expires_at})
        base = ExecutionCommand(
            request=stored,
            fingerprint=request_fingerprint(request),
            state=CommandState.PENDING,
            route=route,
            mode=mode,
            created_at=now,
            expires_at=expires_at,
        )
        if problems:
            rejected = base.model_copy(
                update={
                    "state": CommandState.REJECTED,
                    "completed_at": now,
                    "reject_code": problems[0].code.value,
                    "detail": "; ".join(f"{p.code.value}: {p.detail}" for p in problems),
                }
            )
            await self._persist(rejected, now)
            await self._events.publish(
                ExecutionRejected(
                    account_id=request.account_id, correlation_id=request.command_id,
                    command_id=request.command_id, code=problems[0].code.value, detail=rejected.detail,
                )
            )  # fmt: skip
            return ExecutionOutcome(command=rejected, rejections=problems)

        assert account is not None
        if not await self._persist(base, now):  # another writer created it first: it is the truth
            again = await self._repos.execution.get(request.command_id)
            assert again is not None
            return ExecutionOutcome(command=again, replayed=True)
        await self._events.publish(
            ExecutionCommandCreated(account_id=account.id, correlation_id=request.command_id, command=base)
        )
        if route is ExecutionRoute.CONFIRM and automatic:
            return ExecutionOutcome(command=base, awaiting_confirmation=True)
        return ExecutionOutcome(command=await self._dispatch(base, account))

    @staticmethod
    def _route_for(mode: AutonomyMode, request: ExecutionRequest, *, automatic: bool) -> ExecutionRoute:
        """The route a command takes. A closing or a cancelling issued by a human gesture goes to the agent in **every** mode — OFF, OBSERVE,
        PAPER and HALTED included — like a human exit in CONFIRM: the gesture is the confirmation (ADR 0033, 0034). The way out is never
        closed by the mode. Everything else, and everything automatic, follows the mode: OBSERVE and OFF record and send nothing."""
        if request.kind.reduces_risk_only and not automatic:
            return ExecutionRoute.CONFIRM
        return route_for(mode)

    async def _known(self, account_id: str) -> bool:
        return await self._repos.accounts.get(account_id) is not None

    async def _persist(self, command: ExecutionCommand, now: datetime) -> bool:
        """Persist *before* acting. If the store is down nothing is sent: the caller gets ``Unavailable``."""
        try:
            inserted = await self._repos.execution.insert(command, now)
            self.last_error = None  # the store took a write: whatever failed before is over
            return inserted
        except Unavailable as error:
            self.last_error = error.safe_message
            raise Unavailable(
                "the command could not be recorded, so it was not sent", code=RejectCode.STORE_UNAVAILABLE.value
            ) from error

    async def _validate(
        self,
        request: ExecutionRequest,
        account: Account | None,
        route: ExecutionRoute,
        *,
        automatic: bool,
        now: datetime,
    ) -> list[Rejection]:
        problems: list[Rejection] = []
        connected_id: str | None = None
        login = str(account.login) if account else ""
        if account is not None:
            connected_id = await self._attached_account_id(account)
        decision = None
        if request.risk_decision_id:
            try:
                decision = await self._repos.risk.get_decision(request.risk_decision_id)
            except Unavailable:
                problems.append(Rejection(code=RejectCode.STORE_UNAVAILABLE, detail="the risk decision cannot be read"))
        status = self._link.status(login) if account else None
        sends_to_agent = route in (ExecutionRoute.CONFIRM, ExecutionRoute.AUTOMATIC)
        known = bool(account and self._positions and self._positions.baselined(account.id))
        position = None
        pending = None
        if known and account is not None and self._positions is not None:
            position = next(
                (p for p in self._positions.positions(account.id) if p.position_id == request.position_id), None
            )
            pending = next((o for o in self._positions.orders(account.id) if o.order_id == request.order_id), None)
        context = ValidationContext(
            positions_known=known,
            position=position,
            pending_order=pending,
            now=now,
            automatic=automatic,
            account_exists=account is not None,
            connected_account_id=connected_id,
            active_account_id=self._accounts.active_account_id,
            account_trading_enabled=bool(account and account.trading_enabled),
            agent_registered=status is not None or not sends_to_agent,
            agent_capabilities=frozenset(status.capabilities) if status else frozenset(),
            halted=self._halted() or bool(status and status.halted),
            decision=decision,
        )
        if route is ExecutionRoute.NONE or route is ExecutionRoute.PAPER:
            # nothing is sent in these routes, so the whole protocol can be validated end to end (ADR 0023)
            context = context.model_copy(
                update={"agent_capabilities": frozenset({"modify", "close", "cancel", LIMIT_CAPABILITY})}
            )
        problems += validate(request, context)
        exit_only = request.kind.reduces_risk_only and not automatic
        if (
            status is not None
            and sends_to_agent
            and (refusal := status.command_refusal(exit_only=exit_only)) is not None
        ):
            problems.append(Rejection(code=RejectCode.AGENT_UNREACHABLE, detail=refusal))
        return problems

    async def _attached_account_id(self, account: Account) -> str | None:
        return await self._accounts.attached_account_id(account.id)

    # ------------------------------------------------------------------------------------------ routing
    async def confirm(self, command_id: str) -> ExecutionOutcome:
        """The human gesture CONFIRM mode waits for. Everything is checked again: the world has moved."""
        command = await self._repos.execution.get(command_id)
        if command is None:
            raise NotFound(f"unknown command {command_id!r}", code="command_not_found")
        if command.state is not CommandState.PENDING:
            return ExecutionOutcome(command=command, replayed=True)
        now = self._clock.now()
        account = await self._accounts.effective(command.account_id)
        mode = self._effective_mode(account)
        route = route_for(mode)
        problems = await self._validate(command.request, account, route, automatic=False, now=now)
        if command.expires_at <= now:
            problems.insert(0, Rejection(code=RejectCode.COMMAND_EXPIRED, detail="the command expired while waiting"))
        if route is ExecutionRoute.NONE:
            problems.append(Rejection(code=RejectCode.MODE_NOT_PERMITTING, detail=f"the mode is now {mode.value}"))
        if problems:
            expired = problems[0].code is RejectCode.COMMAND_EXPIRED
            final = await self._move(
                command_id,
                CommandEvent.EXPIRED if expired else CommandEvent.CANCEL_REQUESTED,
                detail="; ".join(f"{p.code.value}: {p.detail}" for p in problems),
                reject_code=problems[0].code.value,
            )
            await self._events.publish(
                ExecutionRejected(
                    account_id=account.id, correlation_id=command_id, command_id=command_id,
                    code=problems[0].code.value, detail="; ".join(p.detail for p in problems),
                )
            )  # fmt: skip
            return ExecutionOutcome(command=final or command, rejections=problems)
        refreshed = command.model_copy(update={"route": route, "mode": mode})
        return ExecutionOutcome(command=await self._dispatch(refreshed, account))

    async def cancel(self, command_id: str) -> ExecutionCommand:
        command = await self._repos.execution.get(command_id)
        if command is None:
            raise NotFound(f"unknown command {command_id!r}", code="command_not_found")
        if command.state is not CommandState.PENDING:
            raise Conflict(f"a {command.state.value} command can no longer be cancelled", code="not_cancellable")
        cancelled = await self._move(command_id, CommandEvent.CANCEL_REQUESTED, detail="cancelled by the user")
        return cancelled or command

    async def _dispatch(self, command: ExecutionCommand, account: Account) -> ExecutionCommand:
        sender = self._senders.get(command.route) or self._senders[ExecutionRoute.NONE]
        if command.route in (ExecutionRoute.NONE, ExecutionRoute.PAPER):
            result = await sender.send(command, account)
            return await self._after_local(command, result)
        result = await sender.send(command, account)
        if result.kind != "sent":
            return await self._failed_unsent(command, result)
        sent = await self._move(command.command_id, CommandEvent.SENT, sent_at=self._clock.now()) or command
        await self._events.publish(
            ExecutionCommandSent(
                account_id=account.id, correlation_id=command.command_id, command_id=command.command_id,
                login_hint=account.id,
            )
        )  # fmt: skip
        return sent

    async def _after_local(self, command: ExecutionCommand, result: SendResult) -> ExecutionCommand:
        request = command.request
        if result.kind == "simulated":
            done = await self._move(
                command.command_id,
                CommandEvent.SIMULATED_LOCALLY,
                detail=result.detail,
                filled_volume=result.filled_volume,
                average_price=result.average_price,
            )
            final = done or command
            await self._events.publish(
                ExecutionReported(
                    account_id=request.account_id, correlation_id=request.command_id, command_id=request.command_id,
                    outcome="simulated", symbol=request.symbol, side=request.side, filled_volume=result.filled_volume,
                    average_price=result.average_price, detail=result.detail,
                )
            )  # fmt: skip
            return final
        return await self._failed_unsent(command, result)

    async def _failed_unsent(self, command: ExecutionCommand, result: SendResult) -> ExecutionCommand:
        failed = await self._move(
            command.command_id,
            CommandEvent.SEND_FAILED,
            detail=result.detail,
            reject_code=RejectCode.AGENT_UNREACHABLE.value,
        )
        await self._events.publish(
            ExecutionFailed(
                account_id=command.account_id, correlation_id=command.command_id, command_id=command.command_id,
                detail=result.detail,
            )
        )  # fmt: skip
        return failed or command

    # ------------------------------------------------------------------------------------------ transitions
    def _lock_for(self, command_id: str) -> asyncio.Lock:
        return self._locks.setdefault(command_id, asyncio.Lock())

    async def _move(self, command_id: str, event: CommandEvent, **fields: object) -> ExecutionCommand | None:
        """Apply one lifecycle event as a compare-and-set. ``None`` when the table has no such edge from the stored
        state (a late or repeated message): nothing changes, and the caller decides whether that matters."""
        async with self._lock_for(command_id):
            current = await self._repos.execution.get(command_id)
            if current is None:
                return None
            try:
                state = next_state(current.state, event)
            except IllegalTransition:
                logger.info("command %s: %s ignored in state %s", command_id, event.value, current.state.value)
                return None
            now = self._clock.now()
            changes: dict[str, object] = {"state": state, **fields}
            if is_terminal(state):
                changes.setdefault("completed_at", now)
            updated = current.model_copy(update=changes)
            await self._repos.execution.transition(current, updated, event.value, now)
            return updated

    # ------------------------------------------------------------------------------------------ the agent talks back
    async def on_registered(self, status: AgentStatus) -> None:
        self._last_beat[status.account_login] = self._clock.now()
        account_id = await self._account_for_login(status.account_login)
        await self._events.publish(AgentConnected(account_id=account_id, status=status))

    async def on_unregistered(self, login: str) -> None:
        self._last_beat.pop(login, None)
        await self._events.publish(
            AgentDisconnected(account_id=await self._account_for_login(login), agent_login=login)
        )

    async def on_status_changed(self, status: AgentStatus) -> None:
        await self._events.publish(
            AgentStatusChanged(account_id=await self._account_for_login(status.account_login), status=status)
        )

    async def on_heartbeat(self, login: str, beat: AgentHeartbeat) -> None:
        self._last_beat[login] = self._clock.now()
        await self._events.publish(
            AgentHeartbeatReceived(
                account_id=await self._account_for_login(login), agent_id=beat.agent_id, latency_ms=beat.latency_ms
            )
        )

    async def on_refused(self, agent_id: str, reason: str) -> None:
        logger.warning("execution agent %s refused: %s", agent_id, reason)

    async def on_duplicate_refused(self, agent_id: str) -> None:
        logger.warning("a second execution agent %s tried to register: refused", agent_id)

    async def on_ack(self, login: str, ack: ExecutionAck) -> None:
        agent = self._link.status(login)
        now = self._clock.now()
        try:
            await self._repos.execution.record_ack(
                AckRecord(
                    command_id=ack.command_id, agent_id=agent.agent_id if agent else login, status=ack.status,
                    reason=ack.reason, received_at=now,
                )
            )  # fmt: skip
        except Unavailable:
            logger.error("ack for %s could not be recorded: database unavailable", ack.command_id)
        account_id = await self._account_for_login(login)
        if ack.status == "ACCEPTED":
            await self._move(ack.command_id, CommandEvent.ACK_ACCEPTED, acknowledged_at=now)
        elif ack.status == "REJECTED":
            code = (ack.reason or "REJECTED").split(":", 1)[0].strip()[:40]
            await self._move(ack.command_id, CommandEvent.ACK_REJECTED, reject_code=code, detail=ack.reason or "")
            await self._events.publish(
                ExecutionRejected(
                    account_id=account_id, correlation_id=ack.command_id, command_id=ack.command_id, code=code,
                    detail=ack.reason or "rejected by the execution agent",
                )
            )  # fmt: skip
        elif ack.status == "EXPIRED":
            await self._move(ack.command_id, CommandEvent.ACK_EXPIRED, detail="expired before the agent could act")
        await self._events.publish(
            ExecutionAcknowledged(
                account_id=account_id, correlation_id=ack.command_id, command_id=ack.command_id, status=ack.status,
                reason=ack.reason,
            )
        )  # fmt: skip

    async def on_report(self, login: str, report: ExecutionReport) -> None:
        agent = self._link.status(login)
        account_id = await self._account_for_login(login)
        now = self._clock.now()
        reported_at = from_epoch_ms(report.time) if report.time else now
        try:
            await self._repos.execution.record_report(
                ReportRecord(
                    report_id=f"{report.command_id}:{report.status}:{report.time}", command_id=report.command_id,
                    account_id=account_id or login, agent_id=agent.agent_id if agent else login, symbol=report.symbol,
                    side=report.side or "", status=report.status, detail=report.detail, reported_at=reported_at,
                )
            )  # fmt: skip
        except Unavailable:
            logger.error("report for %s could not be recorded: database unavailable", report.command_id)
        command = await self._repos.execution.get(report.command_id)
        if command is None:
            logger.warning("report for an unknown command %s ignored", report.command_id)
            return
        fill = {
            "filled_volume": report.filled_volume,
            "average_price": report.average_price,
            "broker_order_id": report.broker_order_id,
            "broker_position_id": report.broker_position_id,
            "broker_retcode": report.broker_retcode,
            "detail": report.detail,
        }
        if command.state in (CommandState.UNKNOWN, CommandState.RECONCILING):
            await self._settle_in_doubt(command, report, fill)
            return
        if report.status in SUCCESS_REPORT_STATUSES:
            if await self._move(report.command_id, CommandEvent.REPORT_EXECUTED, **fill) is not None:
                await self._publish_executed(account_id, report, "executed")
        elif report.status == "SIMULATED":
            if await self._move(report.command_id, CommandEvent.REPORT_SIMULATED, **fill) is not None:
                await self._publish_executed(account_id, report, "simulated")
        elif report.status in ("FAILED", "REJECTED"):
            await self._report_failure(account_id, report, fill)

    async def _report_failure(
        self, account_id: str | None, report: ExecutionReport, fill: Mapping[str, object]
    ) -> None:
        verdict = classify_failed_report(report.broker_retcode, report.detail)
        if verdict is RetcodeClass.FAILURE:
            if await self._move(report.command_id, CommandEvent.REPORT_FAILED, **fill) is not None:
                await self._events.publish(
                    ExecutionFailed(
                        account_id=account_id, correlation_id=report.command_id, command_id=report.command_id,
                        detail=report.detail, broker_retcode=report.broker_retcode,
                    )
                )  # fmt: skip
            return
        # Ambiguous (timeout, processing error, lost connection, no code): the order may be live. UNKNOWN, never FAILED.
        await self._to_unknown(
            report.command_id, f"ambiguous broker return {report.broker_retcode or 'none'}: {report.detail}"
        )

    async def _publish_executed(self, account_id: str | None, report: ExecutionReport, outcome: str) -> None:
        await self._events.publish(
            ExecutionReported(
                account_id=account_id, correlation_id=report.command_id, command_id=report.command_id,
                outcome="executed" if outcome == "executed" else "simulated", symbol=report.symbol,
                side=side_from_wire(report.side) if report.side else None, filled_volume=report.filled_volume,
                average_price=report.average_price, broker_order_id=report.broker_order_id,
                broker_position_id=report.broker_position_id, detail=report.detail, replayed=report.replayed,
            )
        )  # fmt: skip

    async def _settle_in_doubt(
        self, command: ExecutionCommand, report: ExecutionReport, fill: Mapping[str, object]
    ) -> None:
        """A report that arrives for a command we had lost track of is *evidence*, not a state change: it goes through
        RECONCILING → RECONCILED like any other resolution, with what it says recorded."""
        if command.state is CommandState.UNKNOWN:
            await self._move(command.command_id, CommandEvent.RECONCILIATION_STARTED)
        executed = report.status in SUCCESS_REPORT_STATUSES
        detail = f"reconciled from the agent's late report: {report.status} — {report.detail}"
        await self._move(command.command_id, CommandEvent.RECONCILED, **{**fill, "detail": detail})
        if executed:
            await self._publish_executed(command.account_id, report, "executed")

    async def on_reconciled(self, login: str, reconciled: ExecutionReconciled) -> None:
        account_id = await self._account_for_login(login) or login
        now = self._clock.now()
        record = ReconciliationRecord(
            command_id=reconciled.command_id, account_id=account_id, outcome=reconciled.outcome, symbol=reconciled.symbol,
            side=reconciled.side, broker_order_id=reconciled.broker_order_id,
            broker_position_id=reconciled.broker_position_id, filled_volume=reconciled.filled_volume,
            average_price=reconciled.average_price, broker_retcode=reconciled.broker_retcode,
            attempts=reconciled.attempts, detail=reconciled.detail, reconciled_at=now,
        )  # fmt: skip
        await self.settle(record, source="agent")

    async def settle(
        self, record: ReconciliationRecord, *, source: Literal["agent", "core"]
    ) -> ExecutionCommand | None:
        """Apply what the broker shows about an in-doubt command — the **one** place a command leaves UNKNOWN/RECONCILING,
        whether the evidence comes from the execution agent's own history search or from the core's (``source``).

        The record is kept as the current-state projection of the command; the command moves UNKNOWN → RECONCILING and then
        to RECONCILED, or stays RECONCILING when the search found nothing (« never guesses »). A command that is not in
        doubt any more is left alone: late or repeated evidence changes nothing."""
        label = "the agent" if source == "agent" else "the core"
        try:
            await self._repos.execution.upsert_reconciliation(record)
        except Unavailable:
            logger.error("reconciliation of %s could not be recorded", record.command_id)
        command = await self._repos.execution.get(record.command_id)
        if command is None or command.state not in (CommandState.UNKNOWN, CommandState.RECONCILING):
            return command
        if command.state is CommandState.UNKNOWN:
            await self._move(command.command_id, CommandEvent.RECONCILIATION_STARTED, attempts=record.attempts)
        if record.outcome == "not_found":
            return await self._move(
                command.command_id, CommandEvent.RECONCILIATION_PENDING, attempts=record.attempts,
                detail=f"{source}: not found yet — {record.detail}",
            )  # fmt: skip
        settled = await self._move(
            command.command_id, CommandEvent.RECONCILED, attempts=record.attempts,
            broker_order_id=record.broker_order_id, broker_position_id=record.broker_position_id,
            filled_volume=record.filled_volume, average_price=record.average_price,
            broker_retcode=record.broker_retcode, detail=f"reconciled by {label}: {record.outcome} — {record.detail}",
        )  # fmt: skip
        if settled is None:
            return None
        outcome: Literal["executed", "rejected"] = "executed" if record.outcome == "executed" else "rejected"
        await self._events.publish(
            CommandReconciled(
                account_id=command.account_id, correlation_id=command.command_id, command_id=command.command_id,
                outcome=outcome, source=source, broker_order_id=record.broker_order_id,
                broker_position_id=record.broker_position_id, filled_volume=record.filled_volume,
                average_price=record.average_price, detail=settled.detail,
            )
        )  # fmt: skip
        if outcome == "executed" and (record.broker_position_id or (record.filled_volume or 0) > 0):
            await self._events.publish(
                ExecutionReported(
                    account_id=command.account_id, correlation_id=command.command_id, command_id=command.command_id,
                    outcome="executed", symbol=record.symbol or command.request.symbol,
                    side=side_from_wire(record.side) if record.side else command.request.side,
                    filled_volume=record.filled_volume, average_price=record.average_price,
                    broker_order_id=record.broker_order_id, broker_position_id=record.broker_position_id,
                    detail=settled.detail,
                )
            )  # fmt: skip
        return settled

    async def confirm_position(self, command_id: str) -> ExecutionCommand | None:
        """EXECUTED → RECONCILED: the position the fill report named exists at the broker. The service that compares
        the two worlds calls this; nothing else may close the happy path."""
        return await self._move(command_id, CommandEvent.POSITION_CONFIRMED)

    async def on_position_scan(self, login: str, scan: PositionScan) -> None:
        account_id = await self._account_for_login(login) or login
        try:
            await self._repos.positions.upsert_scan(
                PositionScanRecord(
                    account_id=account_id, broker_position_id=scan.broker_position_id or "", symbol=scan.symbol,
                    side=side_from_wire(scan.side).value, volume=scan.volume, magic_number=scan.magic_number,
                    is_external=scan.is_external, known_command_id=scan.known_command_id,
                    scanned_at=from_epoch_ms(scan.time) if scan.time else self._clock.now(),
                )
            )  # fmt: skip
        except Unavailable:
            logger.warning("position scan not recorded: database unavailable")

    # ------------------------------------------------------------------------------------------ housekeeping
    async def _to_unknown(self, command_id: str, detail: str) -> ExecutionCommand | None:
        updated = await self._move(command_id, CommandEvent.LINK_LOST, detail=detail)
        if updated is not None:
            await self._events.publish(
                ExecutionUnknown(
                    account_id=updated.account_id, correlation_id=command_id, command_id=command_id, detail=detail
                )
            )
        return updated

    async def sweep(self) -> int:
        """Called every few seconds. Expires commands nobody confirmed; turns silence into UNKNOWN (never into FAILED)."""
        now = self._clock.now()
        changed = 0
        for command in await self._repos.execution.in_states([CommandState.PENDING]):
            if (
                command.expires_at <= now
                and await self._move(command.command_id, CommandEvent.EXPIRED, detail="expired unconfirmed") is not None
            ):
                changed += 1
        for command in await self._repos.execution.in_states([CommandState.SENT]):
            if (
                command.sent_at
                and now - command.sent_at > ACK_TIMEOUT
                and await self._to_unknown(command.command_id, "no acknowledgement from the agent") is not None
            ):
                changed += 1
        for command in await self._repos.execution.in_states([CommandState.ACKNOWLEDGED]):
            if (
                command.acknowledged_at
                and now - command.acknowledged_at > REPORT_TIMEOUT
                and await self._to_unknown(command.command_id, "acknowledged but no final report") is not None
            ):
                changed += 1
        return changed

    async def recover(self) -> int:
        """At startup. Unsent commands are stale (expired); anything that may have reached the broker becomes UNKNOWN —
        a restart never replays an order."""
        changed = 0
        for command in await self._repos.execution.in_states([CommandState.PENDING]):
            if (
                await self._move(
                    command.command_id, CommandEvent.EXPIRED, detail="the core restarted before it was sent"
                )
                is not None
            ):
                changed += 1
        for command in await self._repos.execution.in_states([CommandState.SENT, CommandState.ACKNOWLEDGED]):
            if (
                await self._to_unknown(command.command_id, "the core restarted while the outcome was pending")
                is not None
            ):
                changed += 1
        return changed

    def registered_logins(self) -> list[str]:
        """The logins of the execution agents connected right now."""
        return self._link.registered_logins()

    async def halt_agents(self, reason: str) -> int:
        """Set the local kill switch of every connected agent. Lifting it takes a human on the MT5 chart."""
        count = 0
        for login in self._link.registered_logins():
            if await self._link.send_halt(login, reason):
                count += 1
        return count

    # ------------------------------------------------------------------------------------------ reading
    async def get(self, command_id: str) -> ExecutionCommand | None:
        return await self._repos.execution.get(command_id)

    async def recent(self, account_id: str | None = None, limit: int = 50) -> list[ExecutionCommand]:
        return await self._repos.execution.recent(account_id, limit)

    async def in_doubt(self, account_id: str | None = None) -> list[ExecutionCommand]:
        return await self._repos.execution.in_doubt(account_id)
