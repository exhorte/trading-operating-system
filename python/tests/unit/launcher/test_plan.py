"""The start-up plan (ADR 0038, § 4): a pure function from what was observed to what a start would do. Idempotent when everything is
healthy, never a second copy of a component that is already there, and a component that cannot be started is a **blocked** step with
its reason — never a guess. A start-up action depends on the links before it; a component that is already healthy is never gated."""

from __future__ import annotations

import pytest

from tests.unit.launcher.support import REPO, facts, make_config, obs
from trading_os.launcher.model import ComponentState, Reason, Stage, StepAction
from trading_os.launcher.plan import build_plan

ABSENT = ComponentState.ABSENT
HEALTHY = ComponentState.HEALTHY
UNHEALTHY = ComponentState.UNHEALTHY
FOREIGN = ComponentState.FOREIGN
STARTING = ComponentState.STARTING
UNAVAILABLE = ComponentState.UNAVAILABLE

CONFIG = make_config()


def actions(**observed: object) -> dict[Stage, StepAction]:
    plan = build_plan(obs(**observed), CONFIG)  # type: ignore[arg-type]
    return {step.stage: step.action for step in plan.steps}


def test_the_plan_lists_the_stages_in_dependency_order() -> None:
    plan = build_plan(obs(), CONFIG)
    assert [step.stage for step in plan.steps] == [Stage.DATABASE, Stage.SCHEMA, Stage.CORE, Stage.COCKPIT]


class TestNothingIsRunning:
    def test_every_component_is_started_and_the_schema_is_applied(self) -> None:
        plan = build_plan(obs(database=ABSENT, core=ABSENT, cockpit=ABSENT), CONFIG)
        assert {s.stage: s.action for s in plan.steps} == {
            Stage.DATABASE: StepAction.START,
            Stage.SCHEMA: StepAction.MIGRATE,
            Stage.CORE: StepAction.START,
            Stage.COCKPIT: StepAction.START,
        }
        assert not plan.blocked
        assert not plan.changes_nothing

    def test_the_core_starts_in_the_python_directory_and_the_cockpit_in_the_repository_root(self) -> None:
        """The pitfall of start.ps1 (audit D2): the core must not be started from the repository root."""
        plan = build_plan(obs(database=ABSENT, core=ABSENT, cockpit=ABSENT), CONFIG)
        assert plan.step(Stage.CORE).working_directory == str(REPO / "python")
        assert plan.step(Stage.COCKPIT).working_directory == str(REPO)
        assert plan.step(Stage.DATABASE).working_directory is None


class TestEverythingIsAlreadyRunning:
    def test_nothing_is_started_twice(self) -> None:
        plan = build_plan(obs(), CONFIG)
        assert {s.stage: s.action for s in plan.steps} == {
            Stage.DATABASE: StepAction.KEEP,
            Stage.SCHEMA: StepAction.SKIP,
            Stage.CORE: StepAction.KEEP,
            Stage.COCKPIT: StepAction.KEEP,
        }
        assert plan.step(Stage.SCHEMA).reason is Reason.SCHEMA_IN_USE
        assert plan.changes_nothing
        assert plan.starts == ()

    def test_planning_again_gives_the_same_plan(self) -> None:
        assert build_plan(obs(), CONFIG) == build_plan(obs(), CONFIG)

    def test_a_healthy_component_is_kept_even_when_what_it_needs_is_blocked(self) -> None:
        """A core that answers is not touched because Docker looks unreachable from here: only a *start* depends on the links before it."""
        result = actions(database=UNAVAILABLE, core=HEALTHY, cockpit=ABSENT)
        assert result[Stage.DATABASE] is StepAction.BLOCKED
        assert result[Stage.CORE] is StepAction.KEEP
        assert result[Stage.COCKPIT] is StepAction.START


class TestTheDatabase:
    def test_a_starting_database_is_waited_for_not_started_again(self) -> None:
        assert actions(database=STARTING, core=ABSENT, cockpit=ABSENT)[Stage.DATABASE] is StepAction.WAIT

    def test_docker_that_does_not_answer_blocks_the_database_with_its_reason(self) -> None:
        plan = build_plan(
            obs(database=UNAVAILABLE, core=ABSENT, cockpit=ABSENT, environment=facts(docker=False)), CONFIG
        )
        step = plan.step(Stage.DATABASE)
        assert step.action is StepAction.BLOCKED
        assert step.reason is Reason.DOCKER_UNAVAILABLE
        assert plan.blocked

    @pytest.mark.parametrize("state", [FOREIGN, UNHEALTHY])
    def test_a_foreign_or_unhealthy_database_is_never_started_over(self, state: ComponentState) -> None:
        plan = build_plan(obs(database=state, core=ABSENT, cockpit=ABSENT), CONFIG)
        assert plan.step(Stage.DATABASE).action is StepAction.BLOCKED
        assert plan.step(Stage.DATABASE).reason in {Reason.FOREIGN_PROCESS, Reason.UNHEALTHY}

    @pytest.mark.parametrize("state", [FOREIGN, UNHEALTHY, UNAVAILABLE])
    def test_a_blocked_database_stops_everything_that_would_have_to_be_started_after_it(
        self, state: ComponentState
    ) -> None:
        plan = build_plan(obs(database=state, core=ABSENT, cockpit=ABSENT), CONFIG)
        assert plan.step(Stage.SCHEMA).action is StepAction.BLOCKED
        assert plan.step(Stage.SCHEMA).reason is Reason.DEPENDENCY_BLOCKED
        assert plan.step(Stage.CORE).action is StepAction.BLOCKED
        assert plan.step(Stage.CORE).reason is Reason.DEPENDENCY_BLOCKED
        assert plan.step(Stage.COCKPIT).action is StepAction.BLOCKED
        assert plan.starts == ()


class TestTheSchema:
    def test_it_is_applied_when_the_core_is_not_running(self) -> None:
        assert actions(core=ABSENT, cockpit=ABSENT)[Stage.SCHEMA] is StepAction.MIGRATE

    def test_a_missing_python_environment_blocks_it(self) -> None:
        plan = build_plan(obs(core=ABSENT, cockpit=ABSENT, environment=facts(venv=False)), CONFIG)
        assert plan.step(Stage.SCHEMA).action is StepAction.BLOCKED
        assert plan.step(Stage.SCHEMA).reason is Reason.VENV_MISSING


class TestTheCore:
    def test_a_core_that_is_listening_but_unhealthy_is_never_duplicated(self) -> None:
        plan = build_plan(obs(core=UNHEALTHY, cockpit=ABSENT), CONFIG)
        assert plan.step(Stage.CORE).action is StepAction.BLOCKED
        assert plan.step(Stage.CORE).reason is Reason.UNHEALTHY
        assert StepAction.START not in {s.action for s in plan.steps if s.stage is Stage.CORE}

    def test_a_foreign_process_on_its_ports_blocks_it_and_nothing_is_killed(self) -> None:
        plan = build_plan(obs(core=FOREIGN, cockpit=ABSENT), CONFIG)
        assert plan.step(Stage.CORE).action is StepAction.BLOCKED
        assert plan.step(Stage.CORE).reason is Reason.FOREIGN_PROCESS

    def test_a_missing_python_environment_blocks_its_start(self) -> None:
        plan = build_plan(obs(core=ABSENT, cockpit=ABSENT, environment=facts(venv=False)), CONFIG)
        assert plan.step(Stage.CORE).reason is Reason.VENV_MISSING

    def test_a_missing_env_file_blocks_its_start(self) -> None:
        plan = build_plan(obs(core=ABSENT, cockpit=ABSENT, environment=facts(env_file=False)), CONFIG)
        assert plan.step(Stage.CORE).action is StepAction.BLOCKED
        assert plan.step(Stage.CORE).reason is Reason.ENV_FILE_MISSING

    def test_a_core_that_cannot_start_stops_the_cockpit_from_being_started(self) -> None:
        plan = build_plan(obs(core=FOREIGN, cockpit=ABSENT), CONFIG)
        assert plan.step(Stage.COCKPIT).action is StepAction.BLOCKED
        assert plan.step(Stage.COCKPIT).reason is Reason.DEPENDENCY_BLOCKED


class TestTheCockpit:
    def test_a_cockpit_failing_does_not_touch_the_steps_before_it(self) -> None:
        plan = build_plan(obs(cockpit=FOREIGN), CONFIG)
        assert plan.step(Stage.COCKPIT).action is StepAction.BLOCKED
        assert plan.step(Stage.DATABASE).action is StepAction.KEEP
        assert plan.step(Stage.CORE).action is StepAction.KEEP
        assert plan.blocked

    def test_a_foreign_process_on_port_3000_is_never_taken_for_the_cockpit(self) -> None:
        step = build_plan(obs(cockpit=FOREIGN), CONFIG).step(Stage.COCKPIT)
        assert step.reason is Reason.FOREIGN_PROCESS

    def test_a_cockpit_that_listens_but_does_not_answer_is_not_started_again(self) -> None:
        step = build_plan(obs(cockpit=UNHEALTHY), CONFIG).step(Stage.COCKPIT)
        assert step.action is StepAction.BLOCKED
        assert step.reason is Reason.UNHEALTHY

    def test_missing_npm_blocks_its_start(self) -> None:
        plan = build_plan(obs(cockpit=ABSENT, environment=facts(npm=False)), CONFIG)
        assert plan.step(Stage.COCKPIT).reason is Reason.NPM_MISSING


def test_a_plan_with_a_start_is_not_a_no_op_and_lists_what_it_starts() -> None:
    plan = build_plan(obs(cockpit=ABSENT), CONFIG)
    assert [step.stage for step in plan.starts] == [Stage.COCKPIT]
    assert not plan.changes_nothing
    assert not plan.blocked
