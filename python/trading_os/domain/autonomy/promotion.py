"""What has to have been done and measured before asking the system for more autonomy (ADR 0027) — pure.

Criteria of process, never of profit. A criterion that is not measured is not met. The report advises; it blocks nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.primitives import DomainModel


class PromotionPlan(DomainModel):
    """The thresholds — posed, not derived; the user's to rewrite."""

    evaluation_days: int = Field(default=5, ge=1)
    paper_commands: int = Field(default=20, ge=1)
    confirmed_orders: int = Field(default=20, ge=1)
    validation_trades: int = Field(default=100, ge=1)
    max_total_breach: float = Field(default=0.05, ge=0, le=1)
    armed_days: int = Field(default=5, ge=1)


class PromotionFacts(DomainModel):
    """What the core measured. ``None`` = not measured (never read as zero)."""

    limits_configured: bool
    evaluation_days: int
    paper_commands: int
    confirmed_orders: int
    commands_in_doubt: int
    critical_incidents: int
    readiness_ready: bool | None = None
    validation_trades: int | None = None
    validation_p_total_breach: float | None = None
    armed_days_without_halt: int | None = None


class Criterion(DomainModel):
    criterion_id: str
    label: str
    status: Literal["met", "not_met", "not_measured"]
    evidence: str


class PromotionStep(DomainModel):
    from_mode: AutonomyMode
    to_mode: AutonomyMode
    criteria: list[Criterion]
    met: bool
    current: bool = False  # the system is on ``from_mode`` right now


class PromotionReport(DomainModel):
    account_id: str | None
    mode: AutonomyMode
    advisory: bool = True  # ADR 0027: this report blocks nothing
    steps: list[PromotionStep]
    evaluated_at: datetime


def _count(criterion_id: str, label: str, value: int | None, needed: int, unit: str) -> Criterion:
    if value is None:
        return Criterion(criterion_id=criterion_id, label=label, status="not_measured", evidence="not measured")
    return Criterion(
        criterion_id=criterion_id, label=label, status="met" if value >= needed else "not_met",
        evidence=f"{value} {unit} of the {needed} needed",
    )  # fmt: skip


def _flag(criterion_id: str, label: str, ok: bool | None, evidence: str) -> Criterion:
    if ok is None:
        return Criterion(criterion_id=criterion_id, label=label, status="not_measured", evidence="not measured")
    return Criterion(criterion_id=criterion_id, label=label, status="met" if ok else "not_met", evidence=evidence)


def _none(criterion_id: str, label: str, count: int, what: str) -> Criterion:
    return _flag(criterion_id, label, count == 0, f"{count} {what}")


def _breach(facts: PromotionFacts, plan: PromotionPlan) -> Criterion:
    label = f"Monte Carlo: the total loss limit is reached in at most {plan.max_total_breach:.0%} of the paths"
    if facts.validation_p_total_breach is None:
        return Criterion(
            criterion_id="validation_breach",
            label=label,
            status="not_measured",
            evidence="no Monte Carlo result (no report, or no trade was filled)",
        )
    return _flag(
        "validation_breach", label, facts.validation_p_total_breach <= plan.max_total_breach,
        f"{facts.validation_p_total_breach:.1%} of the paths",
    )  # fmt: skip


def promotion_steps(facts: PromotionFacts, plan: PromotionPlan, mode: AutonomyMode) -> list[PromotionStep]:
    limits = _flag(
        "limits_configured",
        "Limits written by the user",
        facts.limits_configured,
        "configured" if facts.limits_configured else "defaults",
    )
    ready = _flag(
        "readiness",
        "Readiness green (the 16 checks)",
        facts.readiness_ready,
        "green" if facts.readiness_ready else "blockers remain",
    )
    doubt = _none("no_doubt", "No command in doubt", facts.commands_in_doubt, "command(s) sent and not settled")
    incidents = _none("no_incident", "No critical incident open", facts.critical_incidents, "critical incident(s) open")
    plans: list[tuple[AutonomyMode, AutonomyMode, list[Criterion]]] = [
        (
            AutonomyMode.OBSERVE, AutonomyMode.PAPER,
            [limits, _count("evaluation_days", f"Strategy evaluated on {plan.evaluation_days} trading days", facts.evaluation_days, plan.evaluation_days, "day(s)"), incidents],
        ),
        (
            AutonomyMode.PAPER, AutonomyMode.CONFIRM,
            [limits, _count("paper_commands", f"{plan.paper_commands} simulated orders through the whole path", facts.paper_commands, plan.paper_commands, "order(s)"), doubt, ready],
        ),
        (
            AutonomyMode.CONFIRM, AutonomyMode.ARMED,
            [
                _count("confirmed_orders", f"{plan.confirmed_orders} orders executed under CONFIRM", facts.confirmed_orders, plan.confirmed_orders, "order(s)"),
                doubt,
                _count("validation_trades", f"A validation of at least {plan.validation_trades} trades", facts.validation_trades, plan.validation_trades, "trade(s)"),
                _breach(facts, plan),
                ready,
            ],
        ),
        (
            AutonomyMode.ARMED, AutonomyMode.AUTONOMOUS,
            [_count("armed_days", f"{plan.armed_days} days ARMED without an emergency stop", facts.armed_days_without_halt, plan.armed_days, "day(s)")],
        ),
    ]  # fmt: skip
    return [
        PromotionStep(
            from_mode=a, to_mode=b, criteria=criteria, met=all(c.status == "met" for c in criteria), current=a is mode
        )
        for a, b, criteria in plans
    ]
