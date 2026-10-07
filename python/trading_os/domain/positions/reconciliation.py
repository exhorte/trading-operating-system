"""Reconciliation: compare what the Trading OS expects with what MT5 reports (mission § 21).

Pure. The service gathers the inputs (commands that executed, positions and orders read from MT5, the agent's
position scan) and acts on the findings. Findings carry a severity the supervisor maps to an action — an unexpected
position opened under *our* magic number with no command behind it is critical (something is trading that should not);
a position the user opened by hand is only a warning, like the EXTERNAL_POSITION of the agent's own scan.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import Field

from trading_os.domain.execution.commands import CommandState
from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.domain.primitives import AccountId, DomainModel, Side, SymbolCode


class MismatchKind(StrEnum):
    ACCOUNT_MISMATCH = "ACCOUNT_MISMATCH"
    POSITION_MISMATCH = "POSITION_MISMATCH"  # volume, stop or target differ
    ORDER_MISMATCH = "ORDER_MISMATCH"
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    UNKNOWN_EXECUTION = "UNKNOWN_EXECUTION"
    MISSING_POSITION = "MISSING_POSITION"
    UNEXPECTED_POSITION = "UNEXPECTED_POSITION"


class MismatchSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ExpectedPosition(DomainModel):
    """What an executed command should have left at the broker."""

    command_id: str
    account_id: AccountId
    symbol: SymbolCode
    side: Side
    volume: float
    stop_loss: float
    take_profit: float
    broker_position_id: str | None = None  # from the fill report; else matched through the agent's scan
    executed_at: datetime


class UnresolvedCommand(DomainModel):
    command_id: str
    state: CommandState
    since: datetime


class ExpectedOrder(DomainModel):
    command_id: str
    symbol: SymbolCode
    side: Side
    volume: float
    price: float


class Mismatch(DomainModel):
    kind: MismatchKind
    severity: MismatchSeverity
    account_id: AccountId
    detail: str
    command_id: str | None = None
    position_id: str | None = None
    field: str | None = None
    expected: str | None = None
    actual: str | None = None
    external: bool = False  # a position the user opened by hand (not ours)


class ReconciliationInput(DomainModel):
    account_id: AccountId
    now: datetime
    connected_account_id: str | None
    expected: Sequence[ExpectedPosition] = ()
    actual: Sequence[Position] = ()
    # position id → command id, from the agent's own scan (it traces each position's comment back to its command)
    command_by_position: Mapping[str, str] = Field(default_factory=dict)
    closed_position_ids: frozenset[str] = frozenset()  # positions known to have closed (stop/target hit)
    our_magic: int | None = None
    unresolved: Sequence[UnresolvedCommand] = ()
    expected_orders: Sequence[ExpectedOrder] = ()
    actual_orders: Sequence[PendingOrder] = ()
    grace: timedelta = timedelta(seconds=30)  # history and positions lag a fill by a moment
    unresolved_after: timedelta = timedelta(seconds=120)
    price_tolerance: float = 1e-6
    volume_tolerance: float = 1e-8


def _differs(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) > tolerance


def _fmt(value: float) -> str:
    return f"{value:g}"


def reconcile(inp: ReconciliationInput) -> list[Mismatch]:
    found: list[Mismatch] = []
    account = inp.account_id

    if inp.connected_account_id != inp.account_id:
        found.append(
            Mismatch(
                kind=MismatchKind.ACCOUNT_MISMATCH,
                severity=MismatchSeverity.CRITICAL,
                account_id=account,
                detail=f"expected account {inp.account_id}, the terminal reports {inp.connected_account_id or 'none'}",
                expected=inp.account_id,
                actual=inp.connected_account_id,
            )
        )
        return found  # nothing else can be trusted against the wrong account

    by_id = {p.position_id: p for p in inp.actual}
    position_for_command = {cmd: pos for pos, cmd in inp.command_by_position.items() if pos in by_id}
    matched: set[str] = set()

    for exp in inp.expected:
        actual = by_id.get(exp.broker_position_id) if exp.broker_position_id else None
        if actual is None:
            traced = position_for_command.get(exp.command_id)
            actual = by_id.get(traced) if traced else None
        if actual is None:
            if exp.broker_position_id in inp.closed_position_ids or inp.now - exp.executed_at < inp.grace:
                continue  # closed by its stop/target, or the fill has not reached the position list yet
            found.append(
                Mismatch(
                    kind=MismatchKind.MISSING_POSITION,
                    severity=MismatchSeverity.CRITICAL,
                    account_id=account,
                    command_id=exp.command_id,
                    position_id=exp.broker_position_id,
                    detail=f"command {exp.command_id} executed but no matching position at the broker",
                )
            )
            continue
        matched.add(actual.position_id)
        found += _compare(exp, actual, inp)

    for position in inp.actual:
        if position.position_id in matched:
            continue
        ours = inp.our_magic is not None and position.magic_number == inp.our_magic
        found.append(
            Mismatch(
                kind=MismatchKind.UNEXPECTED_POSITION,
                severity=MismatchSeverity.CRITICAL if ours else MismatchSeverity.WARNING,
                account_id=account,
                position_id=position.position_id,
                external=not ours,
                detail=(
                    f"{position.symbol} {position.side} {_fmt(position.volume)} lot has no command behind it"
                    + ("" if ours else " (opened outside the Trading OS)")
                ),
            )
        )

    for command in inp.unresolved:
        overdue = inp.now - command.since >= inp.unresolved_after
        found.append(
            Mismatch(
                kind=MismatchKind.UNKNOWN_EXECUTION,
                severity=MismatchSeverity.CRITICAL if overdue else MismatchSeverity.WARNING,
                account_id=account,
                command_id=command.command_id,
                detail=f"command {command.command_id} is {command.state} since {command.since.isoformat()}",
            )
        )

    found += _reconcile_orders(inp)
    return found


def _compare(exp: ExpectedPosition, actual: Position, inp: ReconciliationInput) -> list[Mismatch]:
    found: list[Mismatch] = []
    base = {"account_id": exp.account_id, "command_id": exp.command_id, "position_id": actual.position_id}
    if actual.symbol != exp.symbol:
        found.append(
            Mismatch(
                kind=MismatchKind.SYMBOL_MISMATCH,
                severity=MismatchSeverity.CRITICAL,
                field="symbol",
                expected=exp.symbol,
                actual=actual.symbol,
                detail=f"expected {exp.symbol}, found {actual.symbol}",
                **base,
            )
        )
    if actual.side is not exp.side:
        found.append(
            Mismatch(
                kind=MismatchKind.POSITION_MISMATCH,
                severity=MismatchSeverity.CRITICAL,
                field="side",
                expected=exp.side.value,
                actual=actual.side.value,
                detail="opposite side to the command",
                **base,
            )
        )
    if _differs(actual.volume, exp.volume, inp.volume_tolerance):
        found.append(
            Mismatch(
                kind=MismatchKind.POSITION_MISMATCH,
                severity=MismatchSeverity.WARNING,
                field="volume",
                expected=_fmt(exp.volume),
                actual=_fmt(actual.volume),
                detail=f"volume {_fmt(actual.volume)} instead of {_fmt(exp.volume)}",
                **base,
            )
        )
    if _differs(actual.stop_loss, exp.stop_loss, inp.price_tolerance):
        removed = actual.stop_loss <= 0 < exp.stop_loss
        found.append(
            Mismatch(
                kind=MismatchKind.POSITION_MISMATCH,
                severity=MismatchSeverity.CRITICAL if removed else MismatchSeverity.WARNING,
                field="stop_loss",
                expected=_fmt(exp.stop_loss),
                actual=_fmt(actual.stop_loss),
                detail="the stop was removed"
                if removed
                else f"stop {_fmt(actual.stop_loss)} instead of {_fmt(exp.stop_loss)}",
                **base,
            )
        )
    if _differs(actual.take_profit, exp.take_profit, inp.price_tolerance):
        found.append(
            Mismatch(
                kind=MismatchKind.POSITION_MISMATCH,
                severity=MismatchSeverity.WARNING,
                field="take_profit",
                expected=_fmt(exp.take_profit),
                actual=_fmt(actual.take_profit),
                detail=f"target {_fmt(actual.take_profit)} instead of {_fmt(exp.take_profit)}",
                **base,
            )
        )
    return found


def _reconcile_orders(inp: ReconciliationInput) -> list[Mismatch]:
    found: list[Mismatch] = []
    known = {order.command_id for order in inp.expected_orders}
    seen_comments = {order.comment for order in inp.actual_orders}
    for expected in inp.expected_orders:
        if (
            not any(expected.command_id in order.comment for order in inp.actual_orders)
            and expected.command_id not in seen_comments
        ):
            found.append(
                Mismatch(
                    kind=MismatchKind.ORDER_MISMATCH,
                    severity=MismatchSeverity.WARNING,
                    account_id=inp.account_id,
                    command_id=expected.command_id,
                    detail=f"pending order of command {expected.command_id} not found",
                )
            )
    for order in inp.actual_orders:
        ours = inp.our_magic is not None and order.magic_number == inp.our_magic
        if ours and not any(command_id in order.comment for command_id in known):
            found.append(
                Mismatch(
                    kind=MismatchKind.ORDER_MISMATCH,
                    severity=MismatchSeverity.CRITICAL,
                    account_id=inp.account_id,
                    detail=f"pending order {order.order_id} carries our magic number but no command",
                    position_id=None,
                )
            )
    return found
