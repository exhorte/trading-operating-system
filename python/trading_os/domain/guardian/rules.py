"""The Account Guardian's judgement — pure (ADR 0025): given the use of the loss limits and the positions the core holds, what must be
closed, and what is only worth saying.

Every outcome here is an *exit* or a *message*: the Guardian can neither open nor widen anything, and it never touches a position the
core did not open.
"""

from __future__ import annotations

from pydantic import Field

from trading_os.domain.positions.models import Position
from trading_os.domain.primitives import DomainModel


class GuardianPlan(DomainModel):
    # Share of each loss limit at which the core's positions are flattened. 1.0 = the limit itself, as the user wrote it; lowering it is
    # the user's choice (a prop-firm limit is a failure, so a margin before it is a reasonable thing to want).
    flatten_at_fraction: float = Field(default=1.0, gt=0, le=1)
    # How long a position of the core may be left without a stop before it is closed (the Position Manager has had that time).
    protect_grace_seconds: int = Field(default=30, ge=0)
    # ADR 0032. OFF unless the user switches it on (a new automatic behaviour): the core's resting orders on a symbol whose spread is over the
    # cap HE wrote for it are cancelled. Positions are never closed for a spread — closing in a wide spread is costly and the stop is at the broker.
    cancel_orders_on_wide_spread: bool = False
    # A reconciliation is asked for at most this often per account (it is read-only, but it is not free).
    reconcile_min_interval_seconds: int = Field(default=60, ge=5)


class LimitUse(DomainModel):
    name: str  # "daily loss" | "weekly loss" | "total loss"
    used_percent: float
    limit_percent: float


class GuardianInputs(DomainModel):
    limits: list[LimitUse]
    managed: list[Position]  # opened by the core
    external: list[Position]  # opened by hand or by another tool: never touched
    unprotected_for_seconds: dict[str, float] = Field(
        default_factory=dict
    )  # managed position id -> time without a stop


class GuardianVerdict(DomainModel):
    flatten_all: bool = False
    breached: list[str] = Field(default_factory=list)  # the limits that triggered it, in words
    close_without_stop: list[str] = Field(default_factory=list)  # managed position ids past the grace period
    alerts: list[str] = Field(default_factory=list)

    @property
    def quiet(self) -> bool:
        return not (self.flatten_all or self.close_without_stop or self.alerts)


def breached_limits(limits: list[LimitUse], plan: GuardianPlan) -> list[str]:
    out: list[str] = []
    for limit in limits:
        if limit.limit_percent <= 0:
            continue  # a limit that is not set measures nothing
        if limit.used_percent >= limit.limit_percent * plan.flatten_at_fraction - 1e-9:
            out.append(f"{limit.name} {limit.used_percent:g}% of {limit.limit_percent:g}%")
    return out


def judge(inputs: GuardianInputs, plan: GuardianPlan) -> GuardianVerdict:
    breached = breached_limits(inputs.limits, plan)
    alerts: list[str] = []
    if breached and inputs.external:
        names = ", ".join(f"{p.symbol} {p.position_id}" for p in inputs.external)
        alerts.append(
            f"a limit is reached and {len(inputs.external)} position(s) not opened by the core stay open: {names}"
        )
    if breached:
        return GuardianVerdict(flatten_all=bool(inputs.managed), breached=breached, alerts=alerts)

    close: list[str] = []
    for position in inputs.managed:
        if position.has_stop:
            continue
        waited = inputs.unprotected_for_seconds.get(position.position_id, 0.0)
        if waited >= plan.protect_grace_seconds:
            close.append(position.position_id)
        else:
            alerts.append(f"{position.symbol} {position.position_id} has no stop ({waited:.0f}s)")
    return GuardianVerdict(close_without_stop=close, alerts=alerts)
