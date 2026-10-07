"""Autonomy: explicit transitions, ceiling, lease, halt, readiness (mission § 24–25: « cannot arm when unhealthy »,
« cannot execute when halted »)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trading_os.domain.autonomy.readiness import Fact, ReadinessFacts, evaluate_readiness
from trading_os.domain.autonomy.state import (
    LADDER,
    AutonomyMode,
    AutonomyState,
    ExecutionRoute,
    arm,
    clamp_to_ceiling,
    disarm,
    expire_lease_if_due,
    halt,
    initial_state,
    lowest,
    rank,
    renew_lease,
    route_for,
)
from trading_os.shared.errors import Forbidden, IllegalTransition

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
M = AutonomyMode


def climb(
    state: AutonomyState, *targets: AutonomyMode, ceiling: AutonomyMode = M.AUTONOMOUS, ready: bool = True
) -> AutonomyState:
    for target in targets:
        state = arm(state, target, ceiling=ceiling, now=NOW, ready=ready)
    return state


class TestLadder:
    def test_starts_off_never_armed(self) -> None:
        state = initial_state(NOW)
        assert state.mode is M.OFF and not state.permits_entries and not state.evaluates_strategies

    def test_one_rung_at_a_time(self) -> None:
        state = initial_state(NOW)
        with pytest.raises(IllegalTransition) as caught:
            arm(state, M.CONFIRM, ceiling=M.AUTONOMOUS, now=NOW, ready=True)
        assert caught.value.code == "skipped_rung"
        state = climb(state, M.OBSERVE, M.PAPER, M.CONFIRM)
        assert state.mode is M.CONFIRM and state.last_transition is not None
        assert state.last_transition.from_mode is M.PAPER and state.last_transition.to_mode is M.CONFIRM

    def test_the_ladder_is_the_one_of_the_mission(self) -> None:
        assert [m.value for m in LADDER] == ["OFF", "OBSERVE", "PAPER", "CONFIRM", "ARMED", "AUTONOMOUS"]
        assert rank(M.HALTED) < rank(M.OFF)
        assert lowest(M.AUTONOMOUS, M.OBSERVE) is M.OBSERVE

    def test_cannot_climb_above_the_ceiling_and_the_default_ceiling_is_observe(self) -> None:
        state = climb(initial_state(NOW), M.OBSERVE, ceiling=M.OBSERVE)
        with pytest.raises(Forbidden) as caught:
            arm(state, M.PAPER, ceiling=M.OBSERVE, now=NOW, ready=True)
        assert caught.value.code == "above_ceiling"

    def test_stepping_sideways_or_backwards_through_arm_is_refused(self) -> None:
        state = climb(initial_state(NOW), M.OBSERVE, M.PAPER)
        for target in (M.PAPER, M.OBSERVE, M.OFF):
            with pytest.raises(IllegalTransition) as caught:
                arm(state, target, ceiling=M.AUTONOMOUS, now=NOW, ready=True)
            assert caught.value.code == "not_a_step_up"
        with pytest.raises(IllegalTransition):
            arm(state, M.HALTED, ceiling=M.AUTONOMOUS, now=NOW, ready=True)


class TestReadinessGatesTheAutomaticModes:
    def test_cannot_arm_when_not_ready(self) -> None:
        state = climb(initial_state(NOW), M.OBSERVE, M.PAPER, M.CONFIRM)
        with pytest.raises(Forbidden) as caught:
            arm(state, M.ARMED, ceiling=M.AUTONOMOUS, now=NOW, ready=False)
        assert caught.value.code == "not_ready"

    def test_human_in_the_loop_modes_do_not_need_readiness(self) -> None:
        state = climb(initial_state(NOW), M.OBSERVE, M.PAPER, M.CONFIRM, ready=False)
        assert state.mode is M.CONFIRM

    def test_autonomous_needs_readiness_too(self) -> None:
        armed = climb(initial_state(NOW), M.OBSERVE, M.PAPER, M.CONFIRM, M.ARMED)
        with pytest.raises(Forbidden):
            arm(armed, M.AUTONOMOUS, ceiling=M.AUTONOMOUS, now=NOW, ready=False)
        assert arm(armed, M.AUTONOMOUS, ceiling=M.AUTONOMOUS, now=NOW, ready=True).mode is M.AUTONOMOUS


class TestLease:
    def armed(self) -> AutonomyState:
        return climb(initial_state(NOW), M.OBSERVE, M.PAPER, M.CONFIRM, M.ARMED)

    def test_armed_has_a_lease(self) -> None:
        assert self.armed().lease_until == NOW + timedelta(minutes=30)

    def test_the_lease_can_be_renewed_and_expires_into_confirm_not_halt(self) -> None:
        state = self.armed()
        assert expire_lease_if_due(state, NOW + timedelta(minutes=29)) is state
        later = NOW + timedelta(minutes=10)
        renewed = renew_lease(state, now=later)
        assert renewed.lease_until == later + timedelta(minutes=30)
        expired = expire_lease_if_due(state, NOW + timedelta(minutes=30))
        assert expired.mode is M.CONFIRM and expired.lease_until is None
        assert expired.last_transition is not None and expired.last_transition.reason == "lease expired"

    def test_only_armed_has_a_lease(self) -> None:
        with pytest.raises(IllegalTransition):
            renew_lease(climb(initial_state(NOW), M.OBSERVE), now=NOW)

    def test_autonomous_has_no_lease(self) -> None:
        assert arm(self.armed(), M.AUTONOMOUS, ceiling=M.AUTONOMOUS, now=NOW, ready=True).lease_until is None


class TestHaltAndDisarm:
    def autonomous(self) -> AutonomyState:
        return climb(initial_state(NOW), M.OBSERVE, M.PAPER, M.CONFIRM, M.ARMED, M.AUTONOMOUS)

    def test_a_critical_error_halts_from_autonomous(self) -> None:
        halted = halt(self.autonomous(), reason="reconciliation failed", now=NOW)
        assert halted.mode is M.HALTED and halted.halted_reason == "reconciliation failed"
        assert not halted.permits_entries and not halted.evaluates_strategies

    def test_cannot_execute_when_halted(self) -> None:
        halted = halt(self.autonomous(), reason="x", now=NOW)
        assert route_for(halted.mode) is ExecutionRoute.NONE
        with pytest.raises(IllegalTransition) as caught:
            arm(halted, M.OBSERVE, ceiling=M.AUTONOMOUS, now=NOW, ready=True)
        assert caught.value.code == "halted"

    def test_halt_is_idempotent_and_keeps_the_first_reason(self) -> None:
        once = halt(self.autonomous(), reason="first", now=NOW)
        assert halt(once, reason="second", now=NOW) is once

    def test_leaving_a_halt_takes_an_explicit_acknowledgement_and_lands_on_off(self) -> None:
        halted = halt(self.autonomous(), reason="x", now=NOW)
        with pytest.raises(Forbidden) as caught:
            disarm(halted, now=NOW)
        assert caught.value.code == "ack_required"
        off = disarm(halted, now=NOW, acknowledge=True)
        assert off.mode is M.OFF and off.halted_reason is None

    def test_disarm_steps_down_and_never_up(self) -> None:
        autonomous = self.autonomous()
        assert disarm(autonomous, now=NOW).mode is M.OBSERVE
        assert disarm(autonomous, now=NOW, target=M.CONFIRM).mode is M.CONFIRM
        observe = disarm(autonomous, now=NOW)
        assert disarm(observe, now=NOW, target=M.CONFIRM) is observe  # disarm is not a way up
        with pytest.raises(IllegalTransition):
            disarm(autonomous, now=NOW, target=M.HALTED)

    def test_lowering_the_ceiling_pulls_a_running_mode_down(self) -> None:
        paper = climb(initial_state(NOW), M.OBSERVE, M.PAPER)
        assert clamp_to_ceiling(paper, M.OBSERVE, NOW).mode is M.OBSERVE
        assert clamp_to_ceiling(paper, M.CONFIRM, NOW) is paper
        halted = halt(paper, reason="x", now=NOW)
        assert clamp_to_ceiling(halted, M.OFF, NOW) is halted


class TestRoutes:
    def test_what_each_mode_does_with_an_approved_intent(self) -> None:
        assert route_for(M.OFF) is route_for(M.OBSERVE) is route_for(M.HALTED) is ExecutionRoute.NONE
        assert route_for(M.PAPER) is ExecutionRoute.PAPER
        assert route_for(M.CONFIRM) is ExecutionRoute.CONFIRM
        assert route_for(M.ARMED) is route_for(M.AUTONOMOUS) is ExecutionRoute.AUTOMATIC


class TestReadiness:
    def green(self) -> ReadinessFacts:
        names = ReadinessFacts.model_fields
        return ReadinessFacts(**{name: Fact(ok=True, detail="ok") for name in names})

    def test_all_green_is_ready(self) -> None:
        report = evaluate_readiness(self.green(), NOW)
        assert report.ready and report.blockers == [] and len(report.checks) == 16

    def test_nothing_known_is_not_ready(self) -> None:
        report = evaluate_readiness(ReadinessFacts(), NOW)
        assert not report.ready and len(report.blockers) == 16

    def test_a_single_failed_critical_check_blocks_autonomy(self) -> None:
        for field in ReadinessFacts.model_fields:
            facts = self.green().model_copy(update={field: Fact(ok=False, detail="down")})
            report = evaluate_readiness(facts, NOW)
            assert not report.ready and report.blockers == [field]
            failed = next(c for c in report.checks if c.check_id == field)
            assert failed.detail == "down" and failed.critical

    def test_the_sixteen_checks_of_the_mission(self) -> None:
        ids = [c.check_id for c in evaluate_readiness(self.green(), NOW).checks]
        assert ids[:3] == ["python_core", "database", "mt5_connected"]
        assert "position_management" in ids and "account_limits_configured" in ids and "kill_switch_available" in ids
