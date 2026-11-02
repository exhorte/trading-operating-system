"""The Position Manager's rules (ADR 0023) — pure: what to do with the positions the core opened, given what the broker shows.

It decides **management**, never entries: every action it can ask for either tightens a stop, takes risk off the table, or removes a
pending order. It can neither open a position nor widen a stop, and what it asks goes through the same validation as any command.

It reads *state*, not memory. Whether break-even is done is visible in the stop; whether the partial close is done is visible in the
volume (the position holds less than it opened with); a position that is flat needs no flatting. So running the cycle twice, or after
a restart, asks for nothing twice.

R is measured on the **initial stop** — the stop of the OPEN command — not on the current one: once the stop sits at break-even the
distance to it says nothing about the risk the trade was opened with.
"""

from __future__ import annotations

import math

from pydantic import Field, model_validator

from trading_os.domain.execution.commands import CommandKind
from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.domain.primitives import DomainModel, Side

EPSILON = 1e-9


class ExitPlan(DomainModel):
    """How the trader wants positions managed. Starting values, written in code like ``S01Config``; none is a promise of profit."""

    breakeven_at_r: float | None = Field(default=1.0, gt=0)  # None = never move to break-even
    partial_at_r: float | None = Field(default=None, gt=0)  # None = never take a partial profit
    partial_fraction: float = Field(default=0.5, gt=0, lt=1)  # share of the *opening* volume
    trail_distance_r: float | None = Field(default=None, gt=0)  # None = the stop does not trail
    flat_minutes_before_window_end: int = Field(default=5, ge=0)
    close_outside_windows: bool = True  # a managed position still open outside the trading windows is closed
    pending_max_age_minutes: int = Field(default=30, ge=1)  # a limit order that has not filled by then is cancelled

    @model_validator(mode="after")
    def _partial_after_breakeven(self) -> ExitPlan:
        if (
            self.partial_at_r is not None
            and self.breakeven_at_r is not None
            and self.partial_at_r < self.breakeven_at_r
        ):
            raise ValueError("the partial close comes at or after break-even, not before it")
        return self


class SymbolConstraints(DomainModel):
    volume_step: float = Field(gt=0)
    volume_min: float = Field(gt=0)
    price_decimals: int = Field(ge=0, le=10)


class Quote(DomainModel):
    bid: float
    ask: float


class ManagedPosition(DomainModel):
    """A position the core opened, with what only its opening command knows."""

    position: Position
    initial_stop: float = Field(gt=0)
    initial_volume: float = Field(gt=0)
    command_id: str  # the OPEN command: the ids of what is asked for derive from it


class WindowState(DomainModel):
    in_window: bool
    minutes_to_end: float | None = None  # None outside a window


class ManagementAction(DomainModel):
    code: str  # protect | breakeven | trail | partial | flat_end_of_window | flat_outside_window | cancel_*
    kind: CommandKind  # MODIFY | PARTIAL_CLOSE | CLOSE | CANCEL
    reason: str
    symbol: str
    position_id: str | None = None
    order_id: str | None = None
    stop_loss: float | None = None
    volume: float | None = None


def risk_distance(managed: ManagedPosition) -> float:
    return abs(managed.position.entry_price - managed.initial_stop)


def exit_price(position: Position, quote: Quote) -> float:
    """What closing would get: the bid for a long, the ask for a short."""
    return quote.bid if position.side is Side.BUY else quote.ask


def r_multiple(managed: ManagedPosition, quote: Quote) -> float | None:
    distance = risk_distance(managed)
    if distance <= EPSILON:
        return None
    position = managed.position
    move = exit_price(position, quote) - position.entry_price
    move = move if position.side is Side.BUY else -move
    return move / distance


def _tighter(side: Side, candidate: float, current: float) -> bool:
    """The candidate stop lets the position lose less than the current one."""
    return candidate > current + EPSILON if side is Side.BUY else candidate < current - EPSILON


def _behind_price(side: Side, stop: float, price: float) -> bool:
    return stop < price - EPSILON if side is Side.BUY else stop > price + EPSILON


def _round_stop(side: Side, value: float, decimals: int) -> float:
    """A stop at the symbol's precision: down for a long, up for a short, so rounding never carries it up against the price."""
    factor = 10.0**decimals
    return (
        math.floor(value * factor + EPSILON) / factor
        if side is Side.BUY
        else math.ceil(value * factor - EPSILON) / factor
    )


def plan_position(
    managed: ManagedPosition,
    quote: Quote,
    plan: ExitPlan,
    window: WindowState,
    constraints: SymbolConstraints,
    breakeven_buffer: float,
) -> list[ManagementAction]:
    """What to ask for on one managed position. At most one stop move and one partial close per cycle; a flat order replaces them all."""
    position = managed.position
    side = position.side
    symbol = position.symbol
    pid = position.position_id
    price = exit_price(position, quote)

    flat = _flat_reason(plan, window)
    if flat is not None:
        code, reason = flat
        return [ManagementAction(code=code, kind=CommandKind.CLOSE, reason=reason, symbol=symbol, position_id=pid)]

    actions: list[ManagementAction] = []
    current_stop = position.stop_loss if position.has_stop else None

    # A managed position with no stop has unbounded risk: give it the stop it was opened with, or close it if the price is past that.
    if current_stop is None:
        if _behind_price(side, managed.initial_stop, price):
            return [
                ManagementAction(
                    code="protect", kind=CommandKind.MODIFY, reason="the position has no stop: its opening stop is put back",
                    symbol=symbol, position_id=pid, stop_loss=managed.initial_stop,
                )
            ]  # fmt: skip
        return [
            ManagementAction(
                code="protect", kind=CommandKind.CLOSE, reason="no stop, and the price is already past the opening stop",
                symbol=symbol, position_id=pid,
            )
        ]  # fmt: skip

    r = r_multiple(managed, quote)
    if r is None:
        return actions

    best: tuple[str, str, float] | None = None  # the tightest stop asked for this cycle
    if plan.breakeven_at_r is not None and r >= plan.breakeven_at_r - EPSILON:
        offset = breakeven_buffer if side is Side.BUY else -breakeven_buffer
        target = _round_stop(side, position.entry_price + offset, constraints.price_decimals)
        if _tighter(side, target, current_stop) and _behind_price(side, target, price):
            best = ("breakeven", f"+{r:.2f} R reached: stop to break-even {target:g}", target)
    if plan.trail_distance_r is not None and (plan.breakeven_at_r is None or r >= plan.breakeven_at_r - EPSILON):
        distance = plan.trail_distance_r * risk_distance(managed)
        trailed = price - distance if side is Side.BUY else price + distance
        target = _round_stop(side, trailed, constraints.price_decimals)
        floor_ok = target >= position.entry_price if side is Side.BUY else target <= position.entry_price
        better = best is None or _tighter(side, target, best[2])
        if floor_ok and better and _tighter(side, target, current_stop) and _behind_price(side, target, price):
            best = ("trail", f"stop trails {plan.trail_distance_r:g} R behind the price: {target:g}", target)
    if best is not None:
        code, reason, stop = best
        actions.append(
            ManagementAction(
                code=code, kind=CommandKind.MODIFY, reason=reason, symbol=symbol, position_id=pid, stop_loss=stop
            )
        )

    already_partial = position.volume < managed.initial_volume - constraints.volume_step / 2
    if plan.partial_at_r is not None and r >= plan.partial_at_r - EPSILON and not already_partial:
        volume = _partial_volume(managed.initial_volume, plan.partial_fraction, position.volume, constraints)
        if volume is not None:
            actions.append(
                ManagementAction(
                    code="partial", kind=CommandKind.PARTIAL_CLOSE, symbol=symbol, position_id=pid, volume=volume,
                    reason=f"+{r:.2f} R reached: {volume:g} of {managed.initial_volume:g} lot(s) taken",
                )
            )  # fmt: skip
    return actions


def _partial_volume(
    initial: float, fraction: float, open_volume: float, constraints: SymbolConstraints
) -> float | None:
    step = constraints.volume_step
    wanted = math.floor(initial * fraction / step + EPSILON) * step
    wanted = round(wanted, 8)
    remaining = open_volume - wanted
    if wanted < constraints.volume_min - EPSILON or remaining < constraints.volume_min - EPSILON:
        return None  # the position cannot be split in two valid lots
    return wanted


def _flat_reason(plan: ExitPlan, window: WindowState) -> tuple[str, str] | None:
    if not window.in_window:
        if plan.close_outside_windows:
            return "flat_outside_window", "the position is still open outside the trading windows"
        return None
    if window.minutes_to_end is not None and window.minutes_to_end <= plan.flat_minutes_before_window_end:
        return (
            "flat_end_of_window",
            f"{max(window.minutes_to_end, 0):.0f} min before the window closes: position closed",
        )
    return None


def target_reached_before_fill(order: PendingOrder, quote: Quote | None) -> bool:
    """Note N6 (« nix the trade »): the market reached the objective without coming back to the limit — the setup is gone, the order
    must not wait for a price that no longer means anything. A long's objective is reached by the bid, a short's by the ask."""
    if quote is None or order.take_profit <= 0:
        return False
    return quote.bid >= order.take_profit if order.side is Side.BUY else quote.ask <= order.take_profit


def plan_pending_order(
    order: PendingOrder, plan: ExitPlan, window: WindowState, age_minutes: float | None, quote: Quote | None = None
) -> ManagementAction | None:
    """A limit order that is still resting when it should not be: its objective was reached before it filled (N6), the window is
    closing (or closed), or it waited too long."""
    reason: tuple[str, str] | None = None
    if target_reached_before_fill(order, quote):
        reason = (
            "cancel_target_reached",
            f"the objective {order.take_profit:g} was reached before the order filled: setup void",
        )
    elif not window.in_window:
        reason = ("cancel_outside_window", "the order is resting outside the trading windows")
    elif window.minutes_to_end is not None and window.minutes_to_end <= plan.flat_minutes_before_window_end:
        reason = ("cancel_end_of_window", "the window is about to close: the order is withdrawn")
    elif age_minutes is not None and age_minutes >= plan.pending_max_age_minutes:
        reason = ("cancel_stale", f"the order has rested {age_minutes:.0f} min without filling")
    if reason is None:
        return None
    code, text = reason
    return ManagementAction(
        code=code, kind=CommandKind.CANCEL, reason=text, symbol=order.symbol, order_id=order.order_id
    )
