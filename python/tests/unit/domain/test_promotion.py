"""The criteria for climbing the autonomy ladder (ADR 0027): process, never profit; unmeasured is never met."""

from __future__ import annotations

from trading_os.domain.autonomy.promotion import PromotionFacts, PromotionPlan, promotion_steps
from trading_os.domain.autonomy.state import AutonomyMode

PLAN = PromotionPlan()


def facts(**changes: object) -> PromotionFacts:
    base: dict[str, object] = {
        "limits_configured": True, "evaluation_days": 6, "paper_commands": 25, "confirmed_orders": 30,
        "commands_in_doubt": 0, "critical_incidents": 0, "readiness_ready": True, "validation_trades": 150,
        "validation_p_total_breach": 0.02, "armed_days_without_halt": 7,
    }  # fmt: skip
    base.update(changes)
    return PromotionFacts(**base)


def step(report: list, to: AutonomyMode):  # type: ignore[no-untyped-def]
    return next(s for s in report if s.to_mode is to)


def status(step_, criterion_id: str) -> str:  # type: ignore[no-untyped-def]
    return next(c.status for c in step_.criteria if c.criterion_id == criterion_id)


def test_every_climb_is_met_when_everything_asked_was_done() -> None:
    steps = promotion_steps(facts(), PLAN, AutonomyMode.OBSERVE)
    assert [s.to_mode for s in steps] == [
        AutonomyMode.PAPER,
        AutonomyMode.CONFIRM,
        AutonomyMode.ARMED,
        AutonomyMode.AUTONOMOUS,
    ]
    assert all(s.met for s in steps)


def test_only_the_step_the_system_stands_on_is_current() -> None:
    steps = promotion_steps(facts(), PLAN, AutonomyMode.PAPER)
    assert [s.current for s in steps] == [False, True, False, False]


def test_a_fresh_system_meets_nothing() -> None:
    empty = facts(
        limits_configured=False, evaluation_days=0, paper_commands=0, confirmed_orders=0, readiness_ready=False,
        validation_trades=None, validation_p_total_breach=None, armed_days_without_halt=None,
    )  # fmt: skip
    steps = promotion_steps(empty, PLAN, AutonomyMode.OBSERVE)
    assert not any(s.met for s in steps)
    assert status(step(steps, AutonomyMode.PAPER), "limits_configured") == "not_met"


def test_not_measured_is_never_met() -> None:
    steps = promotion_steps(
        facts(armed_days_without_halt=None, validation_trades=None, validation_p_total_breach=None),
        PLAN,
        AutonomyMode.ARMED,
    )
    assert (
        status(step(steps, AutonomyMode.AUTONOMOUS), "armed_days") == "not_measured"
        and not step(steps, AutonomyMode.AUTONOMOUS).met
    )
    armed = step(steps, AutonomyMode.ARMED)
    assert status(armed, "validation_trades") == "not_measured" and status(armed, "validation_breach") == "not_measured"
    assert not armed.met


def test_the_thresholds_are_the_ones_posed() -> None:
    assert (
        status(
            step(promotion_steps(facts(evaluation_days=4), PLAN, AutonomyMode.OBSERVE), AutonomyMode.PAPER),
            "evaluation_days",
        )
        == "not_met"
    )
    assert (
        status(
            step(promotion_steps(facts(evaluation_days=5), PLAN, AutonomyMode.OBSERVE), AutonomyMode.PAPER),
            "evaluation_days",
        )
        == "met"
    )
    confirm = step(promotion_steps(facts(paper_commands=19), PLAN, AutonomyMode.PAPER), AutonomyMode.CONFIRM)
    assert status(confirm, "paper_commands") == "not_met" and not confirm.met


def test_a_command_in_doubt_or_a_critical_incident_stops_the_climb() -> None:
    assert not step(promotion_steps(facts(commands_in_doubt=1), PLAN, AutonomyMode.PAPER), AutonomyMode.CONFIRM).met
    assert not step(promotion_steps(facts(critical_incidents=1), PLAN, AutonomyMode.OBSERVE), AutonomyMode.PAPER).met


def test_no_criterion_is_about_profit() -> None:
    labels = " ".join(
        c.label.lower() + c.criterion_id
        for s in promotion_steps(facts(), PLAN, AutonomyMode.OBSERVE)
        for c in s.criteria
    )
    assert "profit" not in labels and "pnl" not in labels and "win" not in labels


def test_the_chance_of_hitting_the_total_limit_is_bounded() -> None:
    risky = promotion_steps(facts(validation_p_total_breach=0.20), PLAN, AutonomyMode.CONFIRM)
    assert status(step(risky, AutonomyMode.ARMED), "validation_breach") == "not_met"
    assert (
        status(
            step(
                promotion_steps(facts(validation_p_total_breach=0.05), PLAN, AutonomyMode.CONFIRM), AutonomyMode.ARMED
            ),
            "validation_breach",
        )
        == "met"
    )
