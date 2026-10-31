"""Broker-aware position sizing (ADR 0015: « la taille est calculée depuis les spécifications du courtier »).

Never ``risk / stop_distance`` alone. The loss of a position that travels ``stop_distance`` is

    loss_per_lot = (stop_distance / tick_size) × tick_value_loss          [account currency]

where ``tick_value_loss`` is what the broker reports for the symbol — already converted into the account currency
(a JPY-quoted pair on a USD account, a crypto, gold: each carries its own number). Costs are inside the stop:
the spread widens the distance travelled and the round-trip commission is added per lot (« taille intégrant les
coûts », décision du 2026-09-26).

Rounding **never goes above the budget**: the volume is floored to the broker's step, and when even the minimum
lot would exceed the risk budget the order is refused (``min_volume_exceeds_risk``) — the old calculation floored
at 0.01 lot whatever the stop, silently breaking the risk limit.
"""

from __future__ import annotations

import math
from decimal import ROUND_FLOOR, Decimal

from pydantic import Field

from trading_os.domain.market.models import SymbolSpec
from trading_os.domain.primitives import DomainModel, Side
from trading_os.shared.errors import SizingError


def loss_per_lot(spec: SymbolSpec, stop_distance: float) -> float:
    """Account-currency loss of 1.0 lot if price moves ``stop_distance`` (price units) against the position."""
    if spec.tick_size <= 0 or spec.loss_tick_value <= 0:
        raise SizingError(
            f"{spec.name}: tick size/value missing from the broker specification", code="missing_tick_value"
        )
    return stop_distance / spec.tick_size * spec.loss_tick_value


def commission_in_price(commission_per_lot_round_trip: float, spec: SymbolSpec) -> float:
    """A per-lot commission expressed as a price distance (comparable to spread and stop distance)."""
    if spec.loss_tick_value <= 0:
        return 0.0
    return commission_per_lot_round_trip * spec.tick_size / spec.loss_tick_value


def cost_ratio(spread: float, commission_price: float, stop_distance: float) -> float:
    """S01 cost gate input: round-trip cost ÷ stop distance (``c``). Infinite when there is no stop distance."""
    if stop_distance <= 0:
        return math.inf
    return (spread + commission_price) / stop_distance


def floor_to_step(value: float, step: float) -> float:
    """Floor ``value`` to a multiple of ``step`` without binary-float artefacts (0.29 / 0.01 must be 29 steps)."""
    quotient = (Decimal(str(round(value, 10))) / Decimal(str(step))).to_integral_value(rounding=ROUND_FLOOR)
    return float(quotient * Decimal(str(step)))


class SizingResult(DomainModel):
    volume: float
    risk_budget: float  # account currency the trader allows on this trade
    risk_at_stop: float  # what the chosen volume actually loses at the stop, costs included
    effective_risk_percent: float
    stop_distance: float
    loss_per_lot: float  # incl. spread and commission
    capped: str | None = Field(default=None, description="why the volume was reduced below the raw size, if it was")


def size_position(
    *,
    balance: float,
    risk_percent: float,
    side: Side,
    entry_price: float,
    stop_loss: float,
    spec: SymbolSpec,
    spread: float = 0.0,
    commission_per_lot_round_trip: float = 0.0,
    volume_cap: float | None = None,
) -> SizingResult:
    if balance <= 0:
        raise SizingError("balance must be positive to size a trade", code="invalid_balance")
    if risk_percent <= 0:
        raise SizingError("risk percent must be positive", code="invalid_risk")
    if not spec.trade_allowed:
        raise SizingError(f"{spec.name}: trading is disabled by the broker for this symbol", code="symbol_not_tradable")

    # Prices are quantised to the symbol's digits: round the difference to them, or float noise (1.1000 - 1.0990 =
    # 0.00009999999999998899) turns an exact 1.00 lot into 0.99.
    stop_distance = round((entry_price - stop_loss) * side.direction, spec.digits)
    if stop_distance <= 0:
        raise SizingError("stop loss must be on the losing side of the entry", code="stop_wrong_side")
    min_distance = spec.stops_level_points * spec.point
    if stop_distance < min_distance:
        raise SizingError(
            f"stop distance {stop_distance:g} is under the broker minimum {min_distance:g}", code="stop_too_close"
        )

    per_lot = loss_per_lot(spec, stop_distance + max(spread, 0.0)) + max(commission_per_lot_round_trip, 0.0)
    risk_budget = balance * risk_percent / 100
    raw = risk_budget / per_lot

    ceiling = spec.volume_max
    capped: str | None = None
    if volume_cap is not None and volume_cap < ceiling:
        ceiling, capped = volume_cap, "max_volume_per_order"
    volume = floor_to_step(min(raw, ceiling), spec.volume_step)
    if raw > ceiling:
        capped = capped or "volume_max"
    if volume < spec.volume_min:
        raise SizingError(
            f"{spec.name}: the minimum lot ({spec.volume_min:g}) would risk "
            f"{spec.volume_min * per_lot:.2f}, over the budget of {risk_budget:.2f}",
            code="min_volume_exceeds_risk",
            details={"minVolume": spec.volume_min, "riskBudget": round(risk_budget, 2)},
        )

    risk_at_stop = volume * per_lot
    return SizingResult(
        volume=round(volume, 8),
        risk_budget=round(risk_budget, 2),
        risk_at_stop=round(risk_at_stop, 2),
        effective_risk_percent=round(risk_at_stop / balance * 100, 4),
        stop_distance=round(stop_distance, 10),
        loss_per_lot=round(per_lot, 4),
        capped=capped,
    )
