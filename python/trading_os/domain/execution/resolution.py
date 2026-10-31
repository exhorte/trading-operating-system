"""What the broker shows about a command the core lost track of (UNKNOWN / RECONCILING) — pure.

The execution agent does the same search from inside MetaTrader (``SearchHistoryForCommand`` in the EA) and reports it
as ``execution.reconciled``. The core repeats it from its own read-only view for the cases the agent cannot cover: the
agent is down or was restarted, the link was cut for good, or the answer has to be double-checked. The evidence is the
same — **magic number and comment** — and so are the rules:

* an open position, then the opening deal in history, then a live pending order carrying the command's trace  → *executed*;
* an order in history that carries the trace and was **not** filled (refused, cancelled, expired)             → *rejected*;
* nothing at all                                                                                              → *not found*.

*Not found* is an answer about the searched window, not about the world: the command stays RECONCILING and is looked up
again. It is never turned into FAILED or replayed on this evidence alone — the order may simply not have reached the
history yet. The service decides how long it keeps looking; this function only reports what it sees.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from trading_os.domain.execution.trace import command_trace
from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.domain.primitives import DomainModel, Side, SymbolCode


class BrokerFill(DomainModel):
    """An opening deal from the broker's history, already converted to the domain's vocabulary."""

    position_id: str
    order_id: str
    symbol: SymbolCode
    side: Side
    volume: float
    price: float
    magic: int = 0
    comment: str = ""


class BrokerOrderRecord(DomainModel):
    """An order from the broker's history."""

    order_id: str
    symbol: SymbolCode
    side: Side
    filled: bool
    state: str  # the broker's own word (CANCELED, REJECTED, EXPIRED …), for the record
    magic: int = 0
    comment: str = ""


class BrokerEvidence(DomainModel):
    positions: Sequence[Position] = ()
    pending_orders: Sequence[PendingOrder] = ()
    entry_deals: Sequence[BrokerFill] = ()
    history_orders: Sequence[BrokerOrderRecord] = ()
    our_magic: int | None = None  # None = not known yet: the trace alone (a 64-bit hash) is then the evidence


class CommandResolution(DomainModel):
    outcome: Literal["executed", "rejected", "not_found"]
    found_in: Literal["position", "deal", "pending_order", "order_history", "nowhere"]
    detail: str
    symbol: SymbolCode | None = None
    side: Side | None = None
    broker_order_id: str | None = None
    broker_position_id: str | None = None
    filled_volume: float | None = None
    average_price: float | None = None


def resolve_command(command_id: str, evidence: BrokerEvidence) -> CommandResolution:
    trace = command_trace(command_id)

    def ours(magic: int | None) -> bool:
        return evidence.our_magic is None or magic == evidence.our_magic

    for position in evidence.positions:
        if position.comment == trace and ours(position.magic_number):
            return CommandResolution(
                outcome="executed",
                found_in="position",
                detail=f"position {position.position_id} is open and carries the command's trace",
                symbol=position.symbol,
                side=position.side,
                broker_position_id=position.position_id,
                filled_volume=position.volume,
                average_price=position.entry_price,
            )
    for deal in evidence.entry_deals:
        if deal.comment == trace and ours(deal.magic):
            return CommandResolution(
                outcome="executed",
                found_in="deal",
                detail=f"its opening deal is in the history (position {deal.position_id}); the position is no longer open",
                symbol=deal.symbol,
                side=deal.side,
                broker_order_id=deal.order_id,
                broker_position_id=deal.position_id,
                filled_volume=deal.volume,
                average_price=deal.price,
            )
    for order in evidence.pending_orders:
        if order.comment == trace and ours(order.magic_number):
            return CommandResolution(
                outcome="executed",
                found_in="pending_order",
                detail=f"pending order {order.order_id} is live at the broker and carries the command's trace",
                symbol=order.symbol,
                side=order.side,
                broker_order_id=order.order_id,
                filled_volume=0.0,
            )
    for record in evidence.history_orders:
        if record.comment == trace and ours(record.magic) and not record.filled:
            return CommandResolution(
                outcome="rejected",
                found_in="order_history",
                detail=f"order {record.order_id} reached the broker and ended {record.state}, never filled",
                symbol=record.symbol,
                side=record.side,
                broker_order_id=record.order_id,
                filled_volume=0.0,
            )
    return CommandResolution(
        outcome="not_found",
        found_in="nowhere",
        detail="no open position, pending order, deal or order carries the command's trace in the searched history",
    )
