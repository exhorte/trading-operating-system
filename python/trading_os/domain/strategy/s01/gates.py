"""S01 step 8 — the two viability gates (« portes de viabilité ») (port of ``lib/setup/gates.ts``)::

    c = round-trip cost / stop distance
    R_réel = (R_nominal - c) / (1 + c)

Distinct from the Risk Engine's gates (``domain/risk/gates``), which evaluate safety rules (news, session, drawdown). These decide
whether a setup is even worth proposing; they never touch the Risk Engine and never contour it.

``spread`` and ``commission`` must already be in the same price units as ``stop_distance`` — S01's formula is a pure ratio of price
distances. The wording of the refusals is the original's (the stage reports are compared as text), numbers formatted as JavaScript does.
"""

from __future__ import annotations

import math

from trading_os.domain.primitives import DomainModel, Side
from trading_os.shared.numbers import number_to_string, to_fixed


class ViabilityGateInput(DomainModel):
    entry_price: float
    stop_distance: float
    target_price: float
    side: Side
    spread: float  # live spread at decision time, price units — read live, never averaged
    commission: float  # round-trip commission, price units
    cost_threshold: float  # provisional default 0.25 (S01) until the account profile supplies it
    min_risk_reward: float  # provisional default 3 (S01: at least 1:3)


class ViabilityGateResult(DomainModel):
    cost_ratio: float
    risk_reward_ratio: float
    passed: bool
    reason: str | None


def _divide(numerator: float, denominator: float) -> float:
    """IEEE division as JavaScript does it: a zero stop distance gives an infinite ratio (which the gate refuses), not an error."""
    if denominator == 0:
        if numerator == 0 or numerator != numerator:
            return math.nan
        return math.copysign(math.inf, numerator) * math.copysign(1.0, denominator)
    return numerator / denominator


def evaluate_viability_gates(gate: ViabilityGateInput) -> ViabilityGateResult:
    round_trip_cost = gate.spread + gate.commission
    cost_ratio = _divide(round_trip_cost, gate.stop_distance)

    if cost_ratio > gate.cost_threshold:
        return ViabilityGateResult(
            cost_ratio=cost_ratio, risk_reward_ratio=0.0, passed=False,
            reason=f"porte de coût: c={to_fixed(cost_ratio, 3)} > seuil {number_to_string(gate.cost_threshold)}",
        )  # fmt: skip

    target_distance = abs(gate.target_price - gate.entry_price)
    r_nominal = _divide(target_distance, gate.stop_distance)
    r_real = _divide(r_nominal - cost_ratio, 1 + cost_ratio)

    if r_real < gate.min_risk_reward:
        return ViabilityGateResult(
            cost_ratio=cost_ratio, risk_reward_ratio=r_real, passed=False,
            reason=f"porte R:R: {to_fixed(r_real, 2)} < {number_to_string(gate.min_risk_reward)}",
        )  # fmt: skip

    return ViabilityGateResult(cost_ratio=cost_ratio, risk_reward_ratio=r_real, passed=True, reason=None)
