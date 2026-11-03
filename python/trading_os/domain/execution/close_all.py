"""« Fermer toutes les positions » (ADR 0034): the vocabulary of a close-all batch and the rules that read its outcome.

A batch is **not** a mechanism of its own: it is a set of ordinary ``CLOSE`` (and, if asked, ``CANCEL``) commands that the
execution engine already knows how to send, de-duplicate, acknowledge and reconcile. What this module adds is the *reading*: from
the commands on record and the broker's last picture, say for each target whether it is confirmed closed, still in progress,
refused, simulated or in doubt — and whether the whole is complete. Nothing is called a success until the broker's own picture
agrees and a reconciliation has run after the last settlement.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from trading_os.domain.accounts.models import Environment
from trading_os.domain.autonomy.plan_modes import PlanMode
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.execution.commands import CommandState, ExecutionCommand
from trading_os.domain.execution.reasons import RejectCode
from trading_os.domain.primitives import AccountId, DomainModel, Side

CONFIRMATION = "CLOSE_ALL"  # what the body must say: opening the dialog sends nothing, only this does
BATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{6,24}$")
ID_PREFIX = "ca-"
VERIFY_GRACE = timedelta(
    seconds=45
)  # an executed close the broker's picture still contradicts after this is a mismatch

_PENDING = frozenset({CommandState.PENDING, CommandState.SENT, CommandState.ACKNOWLEDGED})
_IN_DOUBT = frozenset({CommandState.UNKNOWN, CommandState.RECONCILING})
_DONE = frozenset({CommandState.EXECUTED, CommandState.RECONCILED})


def batch_prefix(batch_id: str) -> str:
    return f"{ID_PREFIX}{batch_id}-"


def position_command_id(batch_id: str, position_id: str) -> str:
    """One id per (batch, position): a double click or a replay after an interruption lands on the same command — never a second one."""
    return f"{batch_prefix(batch_id)}{position_id}"


def order_command_id(batch_id: str, order_id: str) -> str:
    return f"{batch_prefix(batch_id)}o{order_id}"


def mask_login(login: int) -> str:
    """The account number as the cockpit shows it: the last four digits only."""
    digits = str(login)
    return "****" + digits[-4:] if len(digits) > 4 else "****"


# ------------------------------------------------------------------------------------------------------ the preview


class CloseAllAccount(DomainModel):
    account_id: AccountId
    name: str
    provider: str
    environment: Environment
    login_masked: str
    server: str
    currency: str
    connected: bool
    mode: AutonomyMode  # what the account is really in; a close works in every one of them
    plan_mode: PlanMode  # the same, in the plan's words (OFF, OBSERVE… LIVE_AUTO, HALTED)
    agent_connected: bool
    agent_magic: int | None = None
    balance: float | None = None
    equity: float | None = None


class CloseAllPosition(DomainModel):
    position_id: str
    symbol: str
    side: Side
    volume: float
    entry_price: float
    current_price: float | None = None
    stop_loss: float = 0.0
    take_profit: float = 0.0
    unrealized_pnl: float = 0.0
    strategy_id: str = "manual"
    closable: bool = True  # the execution agent closes only what carries its magic number (TARGET_NOT_OURS)
    not_closable_reason: str | None = None


class CloseAllOrder(DomainModel):
    order_id: str
    symbol: str
    side: Side
    order_type: str
    volume: float
    price: float
    cancellable: bool = True
    not_cancellable_reason: str | None = None


class CloseAllReason(DomainModel):
    """A stable code the cockpit words in its own language, and the core's sentence as a fallback."""

    code: str
    detail: str


class CloseAllPreview(DomainModel):
    batch_id: str
    generated_at: datetime
    account: CloseAllAccount
    positions: list[CloseAllPosition]
    pending_orders: list[CloseAllOrder]
    total_unrealized_pnl: float
    snapshot_age_seconds: float | None  # how old the picture of the broker is; None = never read
    snapshot_fresh: bool
    blockers: list[CloseAllReason] = Field(
        default_factory=list
    )  # why the confirm button would be pointless (no agent, not connected…)
    warnings: list[CloseAllReason] = Field(default_factory=list)
    can_execute: bool


# ------------------------------------------------------------------------------------------------------ the batch


class CloseAllItemStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"  # persisted / sent / acknowledged, no final report yet
    VERIFYING = "VERIFYING"  # the agent says it is done; the broker's picture does not show it yet
    CONFIRMED = "CONFIRMED"  # done and gone from the broker's picture
    ALREADY_CLOSED = "ALREADY_CLOSED"  # it was not there (any more) when the order came to be sent
    REJECTED = "REJECTED"  # refused by the core or by the agent, with a code
    SIMULATED = "SIMULATED"  # paper or an agent compiled OBSERVE: validated, and nothing was closed at the broker
    UNKNOWN = "UNKNOWN"  # sent, outcome not observed: never replayed, only reconciled
    MISMATCH = "MISMATCH"  # executed according to the agent, still open according to the broker, past the grace
    NOT_CLOSABLE = "NOT_CLOSABLE"  # not the execution agent's to close (foreign magic number): close it in MT5


class CloseAllStatus(StrEnum):
    NOTHING_TO_CLOSE = "NOTHING_TO_CLOSE"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_RECONCILIATION = (
        "AWAITING_RECONCILIATION"  # everything confirmed, the comparison with the broker has not run since
    )
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"  # settled, but something is still open, refused, simulated or in doubt


class CloseAllAction(StrEnum):
    """What the cockpit tells the trader to do next, as a code: the words are the cockpit's."""

    WAIT = "WAIT"
    RECONCILE = "RECONCILE"
    CLOSE_IN_MT5 = "CLOSE_IN_MT5"
    ENABLE_AGENT = "ENABLE_AGENT"
    REVIEW_REJECTIONS = "REVIEW_REJECTIONS"
    CHECK_MT5 = "CHECK_MT5"
    RERUN = "RERUN"


class CloseAllDisposition(StrEnum):
    """What the batch decided about a target at the moment it was run (recorded in the audit trail with the batch)."""

    SENT = "SENT"
    NOT_CLOSABLE = "NOT_CLOSABLE"
    ALREADY_CLOSED = "ALREADY_CLOSED"
    REFUSED = "REFUSED"  # the engine raised before a command existed (store down, id conflict): nothing was sent


class PlannedItem(DomainModel):
    """One target of the batch as decided at the start: kept in the audit event so a report survives a restart."""

    target: Literal["position", "order"]
    target_id: str
    symbol: str
    side: Side | None = None
    volume: float | None = None
    disposition: CloseAllDisposition
    command_id: str | None = None
    reason: str | None = None


class CloseAllItem(DomainModel):
    target: Literal["position", "order"]
    target_id: str
    symbol: str
    side: Side | None = None
    volume: float | None = None
    command_id: str | None = None
    command_state: CommandState | None = None
    status: CloseAllItemStatus
    reject_code: str | None = None
    detail: str = ""
    still_open: bool = False  # the broker's last picture still shows it


class CloseAllCounts(DomainModel):
    detected: int = 0
    confirmed: int = 0
    in_progress: int = 0
    verifying: int = 0
    already_closed: int = 0
    rejected: int = 0
    simulated: int = 0
    unknown: int = 0
    mismatch: int = 0
    not_closable: int = 0
    positions_still_open: int = 0  # every position the broker still shows, in the batch or not
    orders_still_pending: int = 0


class CloseAllFailure(DomainModel):
    reason: str  # a reject code, or the status when there is none
    count: int
    target_ids: list[str]
    detail: str = ""


class CloseAllReport(DomainModel):
    batch_id: str
    account_id: AccountId
    status: CloseAllStatus
    final: bool  # nothing left moving: what is shown will not change by itself
    started_at: datetime | None
    evaluated_at: datetime
    include_pending_orders: bool
    items: list[CloseAllItem]
    counts: CloseAllCounts
    failures: list[CloseAllFailure]
    actions: list[CloseAllAction]
    reconciled: bool  # a readable reconciliation finished after the last settlement, without a critical divergence
    reconciliation_critical: int = 0
    snapshot_fresh: bool = True
    other_open_positions: list[str] = Field(
        default_factory=list
    )  # open at the broker, not part of this batch (opened since)
    simulated_only: bool = False  # every command came back SIMULATED: this batch closed nothing


# ------------------------------------------------------------------------------------------------------ the rules


def classify(
    planned: PlannedItem, command: ExecutionCommand | None, *, still_open: bool, now: datetime
) -> CloseAllItem:
    """Read one target. ``still_open``: the broker's last picture still shows the position (or the pending order)."""
    base: dict[str, Any] = {
        "target": planned.target, "target_id": planned.target_id, "symbol": planned.symbol, "side": planned.side,
        "volume": planned.volume, "command_id": planned.command_id, "still_open": still_open,
    }  # fmt: skip
    if command is None:
        if planned.disposition is CloseAllDisposition.REFUSED:
            return CloseAllItem(status=CloseAllItemStatus.REJECTED, detail=planned.reason or "refused", **base)
        if planned.disposition is CloseAllDisposition.NOT_CLOSABLE:
            status = CloseAllItemStatus.NOT_CLOSABLE if still_open else CloseAllItemStatus.ALREADY_CLOSED
            return CloseAllItem(status=status, detail=planned.reason or "", **base)
        if planned.disposition is CloseAllDisposition.ALREADY_CLOSED or not still_open:
            return CloseAllItem(
                status=CloseAllItemStatus.ALREADY_CLOSED, detail=planned.reason or "not open at the broker", **base
            )
        # sent, but the command row is not there: the batch cannot vouch for it
        return CloseAllItem(status=CloseAllItemStatus.UNKNOWN, detail="the command is not on record", **base)

    state = command.state
    base |= {"command_state": state, "reject_code": command.reject_code}
    if state in _PENDING:
        return CloseAllItem(status=CloseAllItemStatus.IN_PROGRESS, detail=command.detail, **base)
    if state in _IN_DOUBT:
        suffix = " (no longer open at the broker; the command is still to be reconciled)" if not still_open else ""
        return CloseAllItem(status=CloseAllItemStatus.UNKNOWN, detail=command.detail + suffix, **base)
    if state in _DONE:
        if not still_open:
            return CloseAllItem(status=CloseAllItemStatus.CONFIRMED, detail=command.detail, **base)
        completed = command.completed_at or command.created_at
        if now - completed > VERIFY_GRACE:
            return CloseAllItem(
                status=CloseAllItemStatus.MISMATCH,
                detail="the agent reports it done, the broker still shows it open",
                **base,
            )
        return CloseAllItem(
            status=CloseAllItemStatus.VERIFYING, detail="waiting for the broker's picture to agree", **base
        )
    if state is CommandState.SIMULATED:
        if not still_open:
            return CloseAllItem(
                status=CloseAllItemStatus.ALREADY_CLOSED, detail="closed elsewhere; this command only simulated", **base
            )
        return CloseAllItem(
            status=CloseAllItemStatus.SIMULATED, detail="validated end to end; no order reached the broker", **base
        )
    # refused before or by the agent
    if (
        command.reject_code in {RejectCode.POSITION_NOT_FOUND.value, RejectCode.ORDER_NOT_FOUND.value}
        and not still_open
    ):
        return CloseAllItem(status=CloseAllItemStatus.ALREADY_CLOSED, detail=command.detail, **base)
    return CloseAllItem(status=CloseAllItemStatus.REJECTED, detail=command.detail, **base)


def _counts(items: list[CloseAllItem], *, positions_open: int, orders_pending: int) -> CloseAllCounts:
    def n(status: CloseAllItemStatus) -> int:
        return sum(1 for item in items if item.status is status)

    return CloseAllCounts(
        detected=len(items), confirmed=n(CloseAllItemStatus.CONFIRMED), in_progress=n(CloseAllItemStatus.IN_PROGRESS),
        verifying=n(CloseAllItemStatus.VERIFYING), already_closed=n(CloseAllItemStatus.ALREADY_CLOSED), rejected=n(CloseAllItemStatus.REJECTED),
        simulated=n(CloseAllItemStatus.SIMULATED), unknown=n(CloseAllItemStatus.UNKNOWN), mismatch=n(CloseAllItemStatus.MISMATCH),
        not_closable=n(CloseAllItemStatus.NOT_CLOSABLE), positions_still_open=positions_open, orders_still_pending=orders_pending,
    )  # fmt: skip


_PROBLEMS = (
    CloseAllItemStatus.REJECTED, CloseAllItemStatus.UNKNOWN, CloseAllItemStatus.SIMULATED, CloseAllItemStatus.MISMATCH, CloseAllItemStatus.NOT_CLOSABLE,
)  # fmt: skip


def _failures(items: list[CloseAllItem]) -> list[CloseAllFailure]:
    grouped: dict[str, list[CloseAllItem]] = {}
    for item in items:
        if item.status in _PROBLEMS:
            grouped.setdefault(item.reject_code or item.status.value, []).append(item)
    return [
        CloseAllFailure(
            reason=reason, count=len(group), target_ids=[i.target_id for i in group], detail=group[0].detail
        )
        for reason, group in grouped.items()
    ]


def _actions(items: list[CloseAllItem], *, moving: bool, other_open: list[str]) -> list[CloseAllAction]:
    present = {item.status for item in items}
    actions: list[CloseAllAction] = []
    if moving:
        actions.append(CloseAllAction.WAIT)
    if CloseAllItemStatus.UNKNOWN in present:
        actions.append(CloseAllAction.RECONCILE)
    if CloseAllItemStatus.MISMATCH in present:
        actions.append(CloseAllAction.CHECK_MT5)
    if CloseAllItemStatus.SIMULATED in present:
        actions.append(CloseAllAction.ENABLE_AGENT)
    if CloseAllItemStatus.REJECTED in present:
        actions.append(CloseAllAction.REVIEW_REJECTIONS)
    if present & {
        CloseAllItemStatus.NOT_CLOSABLE,
        CloseAllItemStatus.SIMULATED,
        CloseAllItemStatus.REJECTED,
        CloseAllItemStatus.MISMATCH,
    }:
        actions.append(CloseAllAction.CLOSE_IN_MT5)
    if other_open:
        actions.append(CloseAllAction.RERUN)
    return actions


def assess(
    *,
    batch_id: str,
    account_id: str,
    items: list[CloseAllItem],
    include_pending_orders: bool,
    started_at: datetime | None,
    now: datetime,
    reconciled: bool,
    reconciliation_critical: int,
    snapshot_fresh: bool,
    positions_open: int,
    orders_pending: int,
    other_open_positions: list[str],
) -> CloseAllReport:
    """The whole batch from its items. ``COMPLETE`` is reached only when every target is confirmed (or was already gone), the
    broker shows nothing of the batch any more, and a reconciliation has run since — never before."""
    moving = any(item.status in {CloseAllItemStatus.IN_PROGRESS, CloseAllItemStatus.VERIFYING} for item in items)
    problems = any(item.status in _PROBLEMS for item in items)
    if not items:
        status = CloseAllStatus.NOTHING_TO_CLOSE
    elif moving:
        status = CloseAllStatus.IN_PROGRESS
    elif problems:
        status = CloseAllStatus.INCOMPLETE
    elif not (reconciled and snapshot_fresh):
        status = CloseAllStatus.AWAITING_RECONCILIATION
    else:
        status = CloseAllStatus.COMPLETE
    simulated_only = bool(items) and all(
        item.status in {CloseAllItemStatus.SIMULATED, CloseAllItemStatus.ALREADY_CLOSED, CloseAllItemStatus.NOT_CLOSABLE} for item in items
    ) and any(item.status is CloseAllItemStatus.SIMULATED for item in items)  # fmt: skip
    return CloseAllReport(
        batch_id=batch_id, account_id=account_id, status=status,
        final=status in {CloseAllStatus.COMPLETE, CloseAllStatus.INCOMPLETE, CloseAllStatus.NOTHING_TO_CLOSE},
        started_at=started_at, evaluated_at=now, include_pending_orders=include_pending_orders, items=items,
        counts=_counts(items, positions_open=positions_open, orders_pending=orders_pending),
        failures=_failures(items), actions=_actions(items, moving=moving, other_open=other_open_positions),
        reconciled=reconciled, reconciliation_critical=reconciliation_critical, snapshot_fresh=snapshot_fresh,
        other_open_positions=other_open_positions, simulated_only=simulated_only,
    )  # fmt: skip
