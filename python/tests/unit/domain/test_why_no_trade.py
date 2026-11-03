"""« Pourquoi pas de trade ? » (ADR 0028): the reasons the core states, in the order an operator would ask them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from trading_os.domain.autonomy.readiness import ReadinessCheck, ReadinessReport
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.autonomy.why import WhyNoTrade, build_why
from trading_os.domain.guardian.report import GuardianReport
from trading_os.domain.guardian.rules import GuardianVerdict
from trading_os.domain.primitives import Side
from trading_os.domain.risk.state import GateResult
from trading_os.domain.strategy.evaluation import StrategyEvaluation

NOW = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)


def blocked(
    strategy: str = "S01", stage: str = "bias", at: datetime = NOW - timedelta(minutes=1)
) -> StrategyEvaluation:
    return StrategyEvaluation(
        strategy_id=strategy, symbol="EURUSDm", event_at=at, status="blocked", stage=stage, detail="H4/D1 disagree"
    )


def proposed(strategy: str = "S01", at: datetime = NOW - timedelta(minutes=2)) -> StrategyEvaluation:
    return StrategyEvaluation(
        strategy_id=strategy, symbol="EURUSDm", event_at=at, status="proposed", side=Side.BUY, entry_price=1.1,
        stop_loss=1.099, take_profit=1.103, risk_reward_ratio=3.0,
    )  # fmt: skip


def why(mode: AutonomyMode = AutonomyMode.ARMED, **changes: object) -> WhyNoTrade:
    base: dict[str, object] = {
        "account_id": "acc", "mode": mode, "ceiling": AutonomyMode.AUTONOMOUS, "halted_reason": None, "readiness": None,
        "risk": None, "evaluations": [], "guardian": None, "now": NOW,
    }  # fmt: skip
    base.update(changes)
    return build_why(**base)  # type: ignore[arg-type]


def readiness(*failing: str) -> ReadinessReport:
    checks = [ReadinessCheck(check_id=c, label=f"label {c}", ok=False, detail=f"{c} is red") for c in failing]
    checks.append(ReadinessCheck(check_id="python_core", label="Core", ok=True, detail="up"))
    return ReadinessReport(ready=not failing, blockers=list(failing), checks=checks, evaluated_at=NOW)


def risk_status(blocked_gates: list[GateResult] | None = None):  # type: ignore[no-untyped-def]
    from tests.unit.domain.risk.fixtures import NOW as RISK_NOW
    from tests.unit.domain.risk.fixtures import inputs
    from trading_os.domain.risk.evaluate import evaluate_risk_state
    from trading_os.domain.risk.view import to_risk_status

    ins = inputs()
    state = evaluate_risk_state(ins)
    if blocked_gates:
        state = state.model_copy(update={"gates": [*state.gates, *blocked_gates]})
    assert RISK_NOW is not None
    return to_risk_status(state, ins.profile)


def test_the_mode_comes_first_and_an_observing_system_is_a_state_not_a_failure() -> None:
    answer = why(AutonomyMode.OBSERVE)
    assert answer.reasons[0].code == "mode_observe" and answer.reasons[0].blocking and not answer.real_orders_possible
    assert "no order leaves it" in answer.headline


def test_off_and_halted_say_so() -> None:
    assert why(AutonomyMode.OFF).reasons[0].code == "mode_off"
    halted = why(AutonomyMode.HALTED, halted_reason="stop removed at the broker")
    assert halted.reasons[0].code == "mode_halted" and "stop removed" in halted.headline


def test_confirm_waits_for_a_human_but_is_not_blocked() -> None:
    answer = why(AutonomyMode.CONFIRM)
    assert answer.reasons[0].code == "mode_confirm" and not answer.reasons[0].blocking and answer.real_orders_possible


def test_a_closed_risk_gate_blocks_and_keeps_the_gates_own_words() -> None:
    gate = GateResult(gate_id="gate-daily-loss", label="Daily loss guard", state="blocked", detail="5% used of 5%")
    answer = why(AutonomyMode.ARMED, risk=risk_status([gate]))
    assert answer.reasons[0].code == "gate-daily-loss" and "5% used of 5%" in answer.headline
    assert not answer.real_orders_possible


def test_the_readiness_only_blocks_the_automatic_modes() -> None:
    ready = readiness("kill_switch_available")
    assert why(AutonomyMode.ARMED, readiness=ready).reasons[0].blocking
    assert not why(AutonomyMode.CONFIRM, readiness=ready).reasons[-1].blocking
    assert why(AutonomyMode.ARMED, readiness=readiness()).real_orders_possible


def test_the_guardian_is_read_before_the_gates() -> None:
    gate = GateResult(gate_id="gate-news", label="News filter", state="blocked", detail="blackout")
    guardian = GuardianReport(
        account_id="acc", ran=True, at=NOW, verdict=GuardianVerdict(flatten_all=True, breached=["daily loss 5% of 5%"])
    )
    answer = why(AutonomyMode.ARMED, risk=risk_status([gate]), guardian=guardian)
    assert [r.source for r in answer.reasons][:2] == ["guardian", "risk"] and "daily loss" in answer.headline


def test_a_guardian_that_has_not_run_says_nothing() -> None:
    assert why(AutonomyMode.ARMED, guardian=GuardianReport(account_id="acc")).reasons == []


def test_without_a_blocking_reason_the_strategy_is_what_is_left() -> None:
    answer = why(AutonomyMode.ARMED, evaluations=[blocked(stage="range_location")])
    assert answer.real_orders_possible and answer.reasons[0].source == "strategy" and not answer.reasons[0].blocking
    assert "waiting for a setup" in answer.headline and "S01 «range_location»" in answer.headline


def test_a_recent_proposal_is_an_opportunity_and_becomes_the_headline() -> None:
    answer = why(AutonomyMode.ARMED, evaluations=[proposed()])
    assert [o.strategy_id for o in answer.opportunities] == ["S01"]
    assert answer.headline == f"S01 proposes a {Side.BUY.value} on EURUSDm"


def test_an_old_proposal_is_no_longer_an_opportunity_and_a_very_old_evaluation_is_forgotten() -> None:
    old = proposed(at=NOW - timedelta(minutes=20))
    assert why(AutonomyMode.ARMED, evaluations=[old]).opportunities == []
    assert why(AutonomyMode.ARMED, evaluations=[blocked(at=NOW - timedelta(hours=2))]).evaluations == []


def test_each_strategy_keeps_only_its_latest_evaluation() -> None:
    older = blocked(stage="bias", at=NOW - timedelta(minutes=5))
    newer = blocked(stage="sweep", at=NOW - timedelta(minutes=1))
    other = blocked(strategy="S02", stage="bias", at=NOW - timedelta(minutes=2))
    answer = why(AutonomyMode.ARMED, evaluations=[older, newer, other])
    assert sorted((e.strategy_id, e.stage) for e in answer.evaluations) == [("S01", "sweep"), ("S02", "bias")]


def test_no_evaluation_at_all_is_said_plainly() -> None:
    assert "no strategy has evaluated yet" in why(AutonomyMode.ARMED).headline
