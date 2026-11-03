"""« Pourquoi pas de trade ? » (ADR 0028) — the reasons the core already states, put in one order and one sentence. Pure: it computes no rule.

Each reason keeps the words of the component that gave it (the gate's detail, the stage a strategy stopped at, the readiness check). The order
of reading is the order an operator would ask in: is the system even running, is the account protecting itself, is a gate closed, is the
platform ready, and only then — did the strategy see anything.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field

from trading_os.domain.autonomy.readiness import ReadinessReport
from trading_os.domain.autonomy.state import AUTOMATIC_MODES, AutonomyMode
from trading_os.domain.guardian.report import GuardianReport
from trading_os.domain.primitives import DomainModel, Side
from trading_os.domain.risk.view import RiskStatus
from trading_os.domain.strategy.evaluation import StrategyEvaluation

OPPORTUNITY_WINDOW = timedelta(minutes=10)
EVALUATION_WINDOW = timedelta(minutes=30)
REAL_ORDER_MODES = frozenset({AutonomyMode.CONFIRM, AutonomyMode.ARMED, AutonomyMode.AUTONOMOUS})

Source = Literal["mode", "guardian", "risk", "readiness", "strategy"]


class Reason(DomainModel):
    source: Source
    code: str
    detail: str
    blocking: bool  # blocks a real order from leaving the core (an information otherwise)


class Opportunity(DomainModel):
    strategy_id: str
    symbol: str
    side: Side
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    risk_reward_ratio: float | None
    at: datetime


class EvaluationLine(DomainModel):
    strategy_id: str
    symbol: str
    status: Literal["proposed", "blocked"]
    stage: str | None
    detail: str | None
    at: datetime


class WhyNoTrade(DomainModel):
    account_id: str | None
    mode: AutonomyMode
    ceiling: AutonomyMode
    headline: str
    real_orders_possible: bool  # nothing in the list blocks a real order
    reasons: list[Reason] = Field(default_factory=list)
    opportunities: list[Opportunity] = Field(default_factory=list)
    evaluations: list[EvaluationLine] = Field(default_factory=list)
    evaluated_at: datetime


def _mode_reason(mode: AutonomyMode, halted_reason: str | None) -> Reason | None:
    if mode is AutonomyMode.OFF:
        return Reason(source="mode", code="mode_off", detail="the system is OFF: nothing is evaluated", blocking=True)
    if mode is AutonomyMode.HALTED:
        return Reason(
            source="mode", code="mode_halted", detail=f"HALTED — {halted_reason or 'emergency stop'}; a human acknowledges it",
            blocking=True,
        )  # fmt: skip
    if mode is AutonomyMode.OBSERVE:
        return Reason(
            source="mode", code="mode_observe", detail="mode OBSERVE: the core evaluates and records, no order leaves it",
            blocking=True,
        )  # fmt: skip
    if mode is AutonomyMode.PAPER:
        return Reason(
            source="mode",
            code="mode_paper",
            detail="mode PAPER: orders are simulated, none reaches the broker",
            blocking=True,
        )
    if mode is AutonomyMode.CONFIRM:
        return Reason(
            source="mode",
            code="mode_confirm",
            detail="mode CONFIRM: every order waits for your confirmation",
            blocking=False,
        )
    return None


def build_why(
    *,
    account_id: str | None,
    mode: AutonomyMode,
    ceiling: AutonomyMode,
    halted_reason: str | None,
    readiness: ReadinessReport | None,
    risk: RiskStatus | None,
    evaluations: list[StrategyEvaluation],
    guardian: GuardianReport | None,
    now: datetime,
) -> WhyNoTrade:
    reasons: list[Reason] = []
    if (mode_reason := _mode_reason(mode, halted_reason)) is not None:
        reasons.append(mode_reason)

    if guardian is not None and guardian.ran:
        if guardian.verdict.flatten_all or guardian.verdict.breached:
            reasons.append(
                Reason(
                    source="guardian", code="limit_reached", detail="a loss limit is reached: " + "; ".join(guardian.verdict.breached),
                    blocking=True,
                )
            )  # fmt: skip
        reasons += [Reason(source="guardian", code="alert", detail=a, blocking=False) for a in guardian.verdict.alerts]

    if risk is not None:
        reasons += [
            Reason(source="risk", code=g.gate_id, detail=f"{g.label}: {g.detail}", blocking=True)
            for g in risk.gates
            if g.state == "blocked"
        ]
        if risk.lockout_reason and not any(r.source == "risk" for r in reasons):
            reasons.append(Reason(source="risk", code="lockout", detail=risk.lockout_reason, blocking=True))

    if readiness is not None:
        failing = {c.check_id: c for c in readiness.checks if not c.ok}
        for check_id in readiness.blockers or []:
            if check_id in failing:
                check = failing[check_id]
                reasons.append(
                    Reason(
                        source="readiness", code=check_id, detail=f"{check.label}: {check.detail}",
                        blocking=mode in AUTOMATIC_MODES,
                    )
                )  # fmt: skip

    cutoff = now - EVALUATION_WINDOW
    latest: dict[tuple[str, str], StrategyEvaluation] = {}
    for evaluation in sorted(evaluations, key=lambda e: e.event_at):
        if evaluation.event_at >= cutoff:
            latest[(evaluation.strategy_id, evaluation.symbol)] = evaluation
    lines = [
        EvaluationLine(
            strategy_id=e.strategy_id, symbol=e.symbol, status=e.status, stage=e.stage, detail=e.detail, at=e.event_at
        )
        for e in latest.values()
    ]
    for line in lines:
        if line.status == "blocked":
            reasons.append(
                Reason(
                    source="strategy", code=f"{line.strategy_id}:{line.stage}",
                    detail=f"{line.strategy_id} {line.symbol} stopped at «{line.stage}»: {line.detail}", blocking=False,
                )
            )  # fmt: skip

    opportunities = [
        Opportunity(
            strategy_id=e.strategy_id, symbol=e.symbol, side=e.side, entry_price=e.entry_price, stop_loss=e.stop_loss,
            take_profit=e.take_profit, risk_reward_ratio=e.risk_reward_ratio, at=e.event_at,
        )
        for e in latest.values()
        if e.status == "proposed" and e.side is not None and now - e.event_at <= OPPORTUNITY_WINDOW
    ]  # fmt: skip

    blocking = [r for r in reasons if r.blocking]
    if blocking:
        headline = blocking[0].detail
    elif opportunities:
        first = opportunities[0]
        headline = f"{first.strategy_id} proposes a {first.side.value} on {first.symbol}"
    elif lines:
        stages = ", ".join(sorted({f"{ln.strategy_id} «{ln.stage}»" for ln in lines if ln.status == "blocked"}))
        headline = "nothing blocks a trade: waiting for a setup" + (f" (last stopped at {stages})" if stages else "")
    else:
        headline = "nothing blocks a trade, and no strategy has evaluated yet"
    return WhyNoTrade(
        account_id=account_id, mode=mode, ceiling=ceiling, headline=headline, real_orders_possible=not blocking,
        reasons=reasons, opportunities=opportunities, evaluations=lines, evaluated_at=now,
    )  # fmt: skip
