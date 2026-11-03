"""One proposed trade, played forward on the candles that follow it (ADR 0026) — pessimistic where a candle cannot say what came first.

Candles are **bid** prices (what MT5 charts). A limit **buy** fills when the *ask* reaches the limit — the bid is ``spread`` lower — and
fills at the limit; a limit **sell** fills when the bid reaches it. A buy's stop and target are bid levels; a sell's stop and target are
ask levels (``bid + spread``). Costs: the commission (price units, round trip) and the slippage a stop suffers. The spread is not a
separate cost per trade here: it is what makes a buy limit harder to fill, and it is already in the level a sell's stop is hit at.

Pessimism: a candle's order of events is unknown, so the stop is checked before the target; on the candle that fills the order only the
stop can fire; an order that would have seen its target before its price is *invalidated*, never counted as a win.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field

from trading_os.domain.market.models import Candle
from trading_os.domain.market.sessions import (
    DEFAULT_TRADING_WINDOWS,
    TradingWindow,
    minutes_until_window_end,
    window_name_at,
)
from trading_os.domain.positions.manager import (
    ExitPlan,
    ManagedPosition,
    Quote,
    SymbolConstraints,
    WindowState,
    plan_position,
)
from trading_os.domain.positions.models import Position
from trading_os.domain.primitives import DomainModel, Side

Outcome = Literal["target", "stop", "time", "window", "unfilled", "invalidated", "expired"]


class TradeCosts(DomainModel):
    spread: float = Field(default=0.0, ge=0)  # price units, constant (the historical series is not available)
    commission: float = Field(default=0.0, ge=0)  # round trip, price units
    stop_slippage: float = Field(default=0.0, ge=0)  # price units, against the trade, when a stop is hit


class TradeSpec(DomainModel):
    symbol: str
    side: Side
    entry: float
    stop: float
    target: float
    placed_at: datetime  # when the limit order would rest at the broker


class SimulatedTrade(DomainModel):
    spec: TradeSpec
    outcome: Outcome
    filled_at: datetime | None = None
    closed_at: datetime | None = None
    r_net: float | None = None  # None while nothing was filled
    r_gross: float | None = None
    minutes_held: float | None = None
    window: str | None = None  # the trading window the order filled in

    @property
    def taken(self) -> bool:
        return self.r_net is not None


class SimulationSettings(DomainModel):
    max_wait_minutes: int = Field(default=30, ge=1)  # a limit order that has not filled by then is cancelled
    max_hold_minutes: int = Field(default=240, ge=1)
    plan: ExitPlan = Field(default_factory=ExitPlan)
    constraints: SymbolConstraints = Field(
        default_factory=lambda: SymbolConstraints(volume_step=0.01, volume_min=0.01, price_decimals=5)
    )


def _is_buy(spec: TradeSpec) -> bool:
    return spec.side is Side.BUY


def _fills(spec: TradeSpec, c: Candle, costs: TradeCosts) -> bool:
    return c.low + costs.spread <= spec.entry if _is_buy(spec) else c.high >= spec.entry


def _target_reached(spec: TradeSpec, c: Candle, costs: TradeCosts, target: float) -> bool:
    return c.high >= target if _is_buy(spec) else c.low + costs.spread <= target


def _stop_hit(spec: TradeSpec, c: Candle, costs: TradeCosts, stop: float) -> bool:
    return c.low <= stop if _is_buy(spec) else c.high + costs.spread >= stop


def _leg_r(spec: TradeSpec, exit_price: float, risk: float) -> float:
    move = exit_price - spec.entry if _is_buy(spec) else spec.entry - exit_price
    return move / risk


def _close_price(spec: TradeSpec, c: Candle, costs: TradeCosts) -> float:
    """Closing at the market: a long sells at the bid, a short buys back at the ask."""
    return c.close if _is_buy(spec) else c.close + costs.spread


def simulate_trade(
    spec: TradeSpec,
    candles: Sequence[Candle],
    costs: TradeCosts,
    settings: SimulationSettings | None = None,
    windows: Sequence[TradingWindow] = DEFAULT_TRADING_WINDOWS,
) -> SimulatedTrade:
    """``candles``: the M1 candles from ``spec.placed_at`` on, in order. Returns what became of the order, in R of the initial stop."""
    cfg = settings or SimulationSettings()
    risk = abs(spec.entry - spec.stop)
    if risk <= 0:
        return SimulatedTrade(spec=spec, outcome="unfilled")

    stop = spec.stop
    legs: list[tuple[float, float]] = []  # (share of the position, R of that leg)
    remaining = 1.0
    filled_at: datetime | None = None
    window: str | None = None

    for c in candles:
        if c.open_time < spec.placed_at:
            continue
        if filled_at is None:
            if _target_reached(spec, c, costs, spec.target) and not _fills(spec, c, costs):
                return SimulatedTrade(spec=spec, outcome="invalidated")
            if not _fills(spec, c, costs):
                if c.open_time - spec.placed_at >= timedelta(minutes=cfg.max_wait_minutes):
                    return SimulatedTrade(spec=spec, outcome="expired")
                continue
            filled_at = c.open_time
            window = window_name_at(c.open_time, windows)
            if _stop_hit(spec, c, costs, stop):  # fills and stops on the same candle: the stop wins
                return _finish(
                    spec,
                    "stop",
                    [(1.0, _leg_r(spec, _stop_exit(spec, stop, costs), risk))],
                    c,
                    filled_at,
                    window,
                    risk,
                    costs,
                )
            continue  # the fill candle can only stop the trade out, never take profit

        if _stop_hit(spec, c, costs, stop):
            legs.append((remaining, _leg_r(spec, _stop_exit(spec, stop, costs), risk)))
            return _finish(spec, "stop", legs, c, filled_at, window, risk, costs)
        if _target_reached(spec, c, costs, spec.target):
            legs.append((remaining, _leg_r(spec, spec.target, risk)))
            return _finish(spec, "target", legs, c, filled_at, window, risk, costs)

        held = (c.open_time - filled_at).total_seconds() / 60
        close = _close_price(spec, c, costs)
        end_of = c.open_time + timedelta(minutes=1)
        state = WindowState(
            in_window=window_name_at(end_of, windows) is not None, minutes_to_end=_minutes_to_end(end_of, windows)
        )
        if held >= cfg.max_hold_minutes:
            legs.append((remaining, _leg_r(spec, close, risk)))
            return _finish(spec, "time", legs, c, filled_at, window, risk, costs)

        position = Position(
            position_id="sim", account_id="sim", symbol=spec.symbol, side=spec.side, volume=remaining,
            entry_price=spec.entry, current_price=close, stop_loss=stop, take_profit=spec.target,
        )  # fmt: skip
        quote = Quote(bid=c.close, ask=c.close + costs.spread)
        actions = plan_position(
            ManagedPosition(position=position, initial_stop=spec.stop, initial_volume=1.0, command_id="sim"),
            quote, cfg.plan, state, cfg.constraints, costs.spread + costs.commission,
        )  # fmt: skip
        for action in actions:
            if action.kind.value == "CLOSE":
                legs.append((remaining, _leg_r(spec, close, risk)))
                return _finish(spec, "window", legs, c, filled_at, window, risk, costs)
            if action.kind.value == "MODIFY" and action.stop_loss is not None:
                stop = action.stop_loss
            if action.kind.value == "PARTIAL_CLOSE" and action.volume is not None:
                share = min(action.volume, remaining)
                legs.append((share, _leg_r(spec, close, risk)))
                remaining -= share

    if filled_at is None:
        return SimulatedTrade(spec=spec, outcome="unfilled")
    last = candles[-1]
    legs.append((remaining, _leg_r(spec, _close_price(spec, last, costs), risk)))
    return _finish(spec, "time", legs, last, filled_at, window, risk, costs)


def _stop_exit(spec: TradeSpec, stop: float, costs: TradeCosts) -> float:
    return stop - costs.stop_slippage if _is_buy(spec) else stop + costs.stop_slippage


def _minutes_to_end(ts: datetime, windows: Sequence[TradingWindow]) -> float | None:
    return minutes_until_window_end(ts, windows)


def _finish(
    spec: TradeSpec,
    outcome: Outcome,
    legs: list[tuple[float, float]],
    last: Candle,
    filled_at: datetime,
    window: str | None,
    risk: float,
    costs: TradeCosts,
) -> SimulatedTrade:
    gross = sum(share * r for share, r in legs)
    net = gross - costs.commission / risk
    return SimulatedTrade(
        spec=spec, outcome=outcome, filled_at=filled_at, closed_at=last.open_time + timedelta(minutes=1),
        r_gross=round(gross, 6), r_net=round(net, 6),
        minutes_held=(last.open_time + timedelta(minutes=1) - filled_at).total_seconds() / 60, window=window,
    )  # fmt: skip
