"""Dynamic risk per trade (ADR 0019): how much **one new trade** may risk, as a percent of the sizing base.

The allowance is the **minimum** of independent caps, never a value of its own — the strictest rule wins:

1. the *grid*: a step function of the account's performance against its **initial capital** (no interpolation);
2. the *absolute-loss trigger*: equity at least ``absolute_loss_trigger_amount`` under the initial capital caps the
   risk at ``absolute_loss_risk_cap_percent``. It is a cap: it never raises a risk the grid already made lower;
3. the profile's per-trade ceiling;
4. the loss budgets that are *left* (day, week, total): limit − loss already taken − risk still open at the stops;
5. N8's reduction, when it is switched on and has its smallest unit (ADR 0031): a cap in whole 0.1 % units, 0 = no new trade.

The grid row is the whole-percent level the performance has **reached**, truncated toward zero (−1.9 % is the −1 %
row, −2.0 % the −2 % row, +0.9 % the « initial capital » row). Pure functions only: the same numbers give the same
answer, which is what makes the decision explainable and testable.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

from pydantic import Field, model_validator

from trading_os.domain.primitives import DomainModel

PERFORMANCE_PRECISION = 6  # decimals: -2.0000000000000018 % must read as the -2 % row, not the -1 % one
RISK_PRECISION = 10_000  # allowance floored to 0.0001 % — flooring never exceeds a cap
NOISE_DECIMALS = 9


class GridTier(DomainModel):
    level_percent: int  # whole-percent performance level; the top row stands for « this level and more »
    risk_percent: float | None = Field(default=None, gt=0)  # None = no new entry at this level (the stop row)


# (level, risk %) — the mission's grid, §6.2. 0.1 % / 0.2 % / 0.3 % rise as the loss deepens: applied as written.
_OFFICIAL_GRID: tuple[tuple[int, float | None], ...] = (
    (5, 1.5),
    (4, 1.5),
    (3, 1.5),
    (2, 1.5),
    (1, 1.5),
    (0, 1.0),
    (-1, 1.0),
    (-2, 0.1),
    (-3, 0.2),
    (-4, 0.3),
    (-5, None),
)
OFFICIAL_GRID = tuple(GridTier(level_percent=level, risk_percent=risk) for level, risk in _OFFICIAL_GRID)


class DynamicRiskPolicy(DomainModel):
    grid: tuple[GridTier, ...] = OFFICIAL_GRID
    # Equity this far under the initial capital (account currency) caps the risk. A cap, never a raise.
    absolute_loss_trigger_amount: float = Field(default=200.0, gt=0)
    absolute_loss_risk_cap_percent: float = Field(default=1.0, gt=0)

    @model_validator(mode="after")
    def _grid_is_safe(self) -> DynamicRiskPolicy:
        levels = [tier.level_percent for tier in self.grid]
        if not levels or levels != list(range(max(levels), min(levels) - 1, -1)):
            raise ValueError("the risk grid needs one row per whole percent, from the highest level to the lowest")
        if self.grid[-1].risk_percent is not None:
            raise ValueError(
                "the lowest row of the risk grid must be a stop (no risk): a loss must always end somewhere"
            )
        if any(tier.risk_percent is None for tier in self.grid[:-1]):
            raise ValueError("only the lowest row of the risk grid may be a stop")
        return self

    @property
    def stop_level_percent(self) -> int:
        return self.grid[-1].level_percent

    @property
    def ceiling_percent(self) -> float:
        return max(tier.risk_percent or 0.0 for tier in self.grid)

    def tier_for(self, performance_percent: float) -> GridTier:
        """The row the performance has reached: whole-percent level, truncated toward zero, clipped to the grid."""
        level = math.trunc(round(performance_percent, PERFORMANCE_PRECISION))
        top, bottom = self.grid[0].level_percent, self.grid[-1].level_percent
        return self.grid[top - min(max(level, bottom), top)]


class RemainingBudget(DomainModel):
    """A loss limit and what is already gone from it. Open risk counts in full: it can still be lost."""

    code: str  # stable id of the cap this budget produces, e.g. ``daily_budget``
    label: str
    limit_percent: float
    used_percent: float
    open_risk_percent: float = 0.0

    @property
    def remaining_percent(self) -> float:
        return self.limit_percent - self.used_percent - self.open_risk_percent


class AppliedCap(DomainModel):
    code: str
    limit_percent: float
    detail: str


AllowanceStatus = Literal["allowed", "stopped", "unavailable"]


class RiskAllowance(DomainModel):
    """What a new trade may risk right now, and why — every cap that was weighed, the one that decided, the reason when
    the answer is no. Persisted with the decision (``RiskDecision.allowance``)."""

    status: AllowanceStatus
    risk_percent: float  # the final value; 0 unless ``status == "allowed"``
    performance_percent: float | None
    tier_level_percent: int | None
    grid_percent: float | None
    binding_cap: str | None
    caps: tuple[AppliedCap, ...] = ()
    reason: str | None = None  # stable machine code when not allowed
    detail: str


def _refuse(
    status: AllowanceStatus,
    reason: str,
    detail: str,
    *,
    performance: float | None = None,
    tier: GridTier | None = None,
    caps: Sequence[AppliedCap] = (),
) -> RiskAllowance:
    return RiskAllowance(
        status=status,
        risk_percent=0.0,
        performance_percent=None if performance is None else round(performance, 4),
        tier_level_percent=tier.level_percent if tier else None,
        grid_percent=tier.risk_percent if tier else None,
        binding_cap=None,
        caps=tuple(caps),
        reason=reason,
        detail=detail,
    )


def performance_percent(initial_capital: float, equity: float) -> float:
    return (equity - initial_capital) / initial_capital * 100


def resolve_risk_allowance(
    policy: DynamicRiskPolicy,
    *,
    initial_capital: float | None,
    equity: float,
    per_trade_ceiling_percent: float,
    budgets: Sequence[RemainingBudget] = (),
    extra_caps: Sequence[AppliedCap] = (),
) -> RiskAllowance:
    if initial_capital is None or initial_capital <= 0:
        return _refuse(
            "unavailable",
            "reference_capital_not_fixed",
            "no initial capital recorded for this account — the grid is measured against it, never against the balance",
        )
    if equity <= 0:
        return _refuse("unavailable", "equity_unknown", "no equity reading for this account")

    performance = performance_percent(initial_capital, equity)
    tier = policy.tier_for(performance)
    if tier.risk_percent is None:
        return _refuse(
            "stopped",
            "performance_stop_reached",
            f"performance {performance:+.2f} % reached the {policy.stop_level_percent} % stop: no new entry",
            performance=performance,
            tier=tier,
        )

    caps = [
        AppliedCap(
            code="grid",
            limit_percent=tier.risk_percent,
            detail=f"performance {performance:+.2f} % → {tier.level_percent:+d} % row",
        ),
        AppliedCap(
            code="per_trade_ceiling",
            limit_percent=per_trade_ceiling_percent,
            detail=f"profile ceiling {per_trade_ceiling_percent:g} %",
        ),
    ]
    shortfall = round(initial_capital - equity, 2)
    if shortfall >= policy.absolute_loss_trigger_amount:
        caps.append(
            AppliedCap(
                code="absolute_loss_trigger",
                limit_percent=policy.absolute_loss_risk_cap_percent,
                detail=f"equity {shortfall:.2f} under the initial capital (trigger {policy.absolute_loss_trigger_amount:g})",
            )
        )
    caps += [
        AppliedCap(
            code=budget.code,
            limit_percent=max(0.0, budget.remaining_percent),
            detail=(
                f"{budget.label}: {budget.limit_percent:g} % − {budget.used_percent:.2f} % lost "
                f"− {budget.open_risk_percent:.2f} % open"
            ),
        )
        for budget in budgets
    ]
    # Caps that only ever LOWER what a trade may risk (N8, ADR 0031): one more entry in the minimum, never a value of its own, never a raise.
    caps += list(extra_caps)

    binding = min(caps, key=lambda cap: cap.limit_percent)  # ties keep the first: the grid is named before the others
    # Floor, never round up — after removing float noise (5.0 − 4.4 is 0.5999999999999996, not a reason to lose 0.0001).
    risk = math.floor(round(binding.limit_percent, NOISE_DECIMALS) * RISK_PRECISION) / RISK_PRECISION
    if risk <= 0:
        return _refuse(
            "stopped",
            "risk_budget_exhausted",
            f"{binding.code}: nothing left to risk ({binding.detail})",
            performance=performance,
            tier=tier,
            caps=caps,
        )
    return RiskAllowance(
        status="allowed",
        risk_percent=risk,
        performance_percent=round(performance, 4),
        tier_level_percent=tier.level_percent,
        grid_percent=tier.risk_percent,
        binding_cap=binding.code,
        caps=tuple(caps),
        detail=f"{risk:g} % ({binding.code}: {binding.detail})",
    )


__all__ = [
    "OFFICIAL_GRID",
    "AppliedCap",
    "DynamicRiskPolicy",
    "GridTier",
    "RemainingBudget",
    "RiskAllowance",
    "performance_percent",
    "resolve_risk_allowance",
]
