"""Starting the application (ADR 0038, § 4): the links in dependency order, each one waited for until it is **really** healthy; nothing started
twice; a link that fails stops what depends on it and nothing else; and whatever the launcher starts is written to its registry before it is
waited for. Run against a simulated machine (``world.py``): no real process, container or port."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.unit.launcher.support import T0
from tests.unit.launcher.world import World
from trading_os.launcher.events import EventType
from trading_os.launcher.model import (
    Component,
    ComponentState,
    ContainerInfo,
    OutcomeStatus,
    Ownership,
    Stage,
)
from trading_os.shared.logging.redaction import clear_secrets, register_secret

DONE, KEPT, SKIPPED, BLOCKED, FAILED = (
    OutcomeStatus.DONE,
    OutcomeStatus.KEPT,
    OutcomeStatus.SKIPPED,
    OutcomeStatus.BLOCKED,
    OutcomeStatus.FAILED,
)


@pytest.fixture
def world(tmp_path: Path) -> World:
    w = World(tmp_path)
    w.container = ContainerInfo(name=w.config.container_name, status="exited", health=None, host_ports=())
    return w


def statuses(report) -> dict[Stage, OutcomeStatus]:  # type: ignore[no-untyped-def]
    return {item.stage: item.status for item in report.outcomes}


def order(world: World) -> list[str]:
    """The effects, in the order they happened, by kind."""
    return [str(call[0]) for call in world.calls]


class TestFromNothing:
    def test_every_link_is_started_in_order_and_ends_healthy(self, world: World) -> None:
        report = world.starter().start()
        assert statuses(report) == {Stage.DATABASE: DONE, Stage.SCHEMA: SKIPPED, Stage.CORE: DONE, Stage.COCKPIT: DONE}
        assert report.ok
        assert world.core_up and world.cockpit_up
        kinds = order(world)
        assert kinds.index("docker.start") < kinds.index("run") < kinds.index("spawn")

    def test_the_core_starts_from_the_python_directory_with_its_output_in_a_log(self, world: World) -> None:
        world.starter().start()
        core, cockpit = world.did("spawn")
        assert core[1] == (str(world.config.venv_python), "-m", "trading_os", "serve")
        assert core[2] == str(world.config.core_cwd)
        assert Path(str(core[3])).parent == world.config.logs_dir
        assert Path(str(core[3])).name.startswith("core-")
        assert cockpit[1] == ("C:/tools/npm.cmd", "run", "dev")
        assert cockpit[2] == str(world.config.cockpit_cwd)
        assert Path(str(cockpit[3])).name.startswith("cockpit-")

    def test_what_was_started_is_in_the_registry_with_its_identity(self, world: World) -> None:
        world.starter().start()
        snapshot = world.registry.load()
        assert {item.component for item in snapshot.owned} == {Component.CORE, Component.COCKPIT}
        table = {process.pid: process for process in world.table.processes()}
        for item in snapshot.owned:
            assert item.created_at == table[item.pid].created_at
            assert item.correlation_id == "run-1"
            assert item.working_directory
        assert [item.name for item in snapshot.containers] == [world.config.container_name]

    def test_the_core_and_the_cockpit_are_owned_in_the_next_observation(self, world: World) -> None:
        world.starter().start()
        observation = world.observer().observe()
        assert observation.component(Component.CORE).ownership is Ownership.OWNED
        assert observation.component(Component.COCKPIT).ownership is Ownership.OWNED
        assert observation.component(Component.CORE).state is ComponentState.HEALTHY

    def test_the_events_tell_the_story_with_one_correlation_id(self, world: World) -> None:
        world.starter().start()
        events = world.events.read()
        assert {event.type for event in events} >= {
            EventType.STARTUP_DATABASE_READY,
            EventType.STARTUP_CORE_READY,
            EventType.STARTUP_COCKPIT_READY,
            EventType.LAUNCHER_PROCESS_STARTED,
        }
        assert {event.correlation_id for event in events} == {"run-1"}

    def test_a_missing_container_is_created_by_compose(self, world: World) -> None:
        world.container = None
        report = world.starter().start()
        assert report.outcome(Stage.DATABASE).status is DONE
        assert world.did("docker.compose_up")
        assert not world.did("docker.start")

    def test_a_database_that_is_still_starting_is_waited_for_not_started_again(self, world: World) -> None:
        world.container = ContainerInfo(
            name=world.config.container_name, status="running", health="starting", host_ports=(world.config.db_port,)
        )
        world.schedule(5, lambda: setattr(world, "container", world.container.model_copy(update={"health": "healthy"})))  # type: ignore[union-attr]
        report = world.starter().start()
        assert report.ok
        assert not world.did("docker.start")
        assert world.registry.load().containers == (), "the launcher did not start that container, it does not own it"


class TestStartingTwice:
    def test_a_second_start_does_nothing(self, world: World) -> None:
        world.starter().start()
        before = len(world.calls)
        report = world.starter("run-2").start()
        assert statuses(report) == {Stage.DATABASE: KEPT, Stage.SCHEMA: SKIPPED, Stage.CORE: KEPT, Stage.COCKPIT: KEPT}
        assert world.calls[before:] == []

    def test_an_application_started_by_hand_is_left_alone_and_nothing_is_written(
        self, world: World, tmp_path: Path
    ) -> None:
        world.run_everything()
        report = world.starter().start()
        assert statuses(report) == {Stage.DATABASE: KEPT, Stage.SCHEMA: SKIPPED, Stage.CORE: KEPT, Stage.COCKPIT: KEPT}
        assert world.calls == []
        assert not (tmp_path / "04_code" / "var").exists(), "a start that changes nothing writes nothing"

    def test_a_component_that_appears_between_the_plan_and_its_start_is_not_started_over(self, world: World) -> None:
        """Re-observed just before every start: somebody else (or an earlier run) may have started it meanwhile."""
        world.after_docker_start = world.run_everything
        report = world.starter().start()
        assert report.outcome(Stage.CORE).status is KEPT
        assert report.outcome(Stage.COCKPIT).status is KEPT
        assert not world.did("spawn")


class TestTheSchema:
    def test_pending_migrations_are_backed_up_first_then_applied_then_the_core_starts(self, world: World) -> None:
        world.pending = ["0007_something"]
        report = world.starter().start()
        assert report.outcome(Stage.SCHEMA).status is DONE
        kinds = order(world)
        assert kinds.index("docker.dump") < max(
            i for i, call in enumerate(world.calls) if call[0] == "run" and call[1][-1] == "migrate"
        )
        assert kinds.index("docker.dump") < kinds.index("spawn")
        (dump,) = world.did("docker.dump")
        assert Path(str(dump[2])).parent == world.config.backups_dir
        assert Path(str(dump[2])).name.startswith("tradingos-")
        assert {EventType.STARTUP_BACKUP_DONE, EventType.STARTUP_SCHEMA_APPLIED} <= {
            e.type for e in world.events.read()
        }

    def test_the_schema_commands_run_from_the_python_directory(self, world: World) -> None:
        world.pending = ["0007_something"]
        world.starter().start()
        runs = world.did("run")
        assert runs
        assert all(call[2] == str(world.config.core_cwd) for call in runs)
        assert all(call[1][:3] == (str(world.config.venv_python), "-m", "trading_os") for call in runs)

    def test_a_schema_that_is_up_to_date_needs_neither_a_backup_nor_a_migration(self, world: World) -> None:
        world.starter().start()
        assert not world.did("docker.dump")
        assert not [call for call in world.did("run") if call[1][-1] == "migrate"]

    def test_a_backup_that_fails_stops_everything_after_it(self, world: World) -> None:
        world.pending = ["0007_something"]
        world.dump_ok = False
        report = world.starter().start()
        assert report.outcome(Stage.SCHEMA).status is FAILED
        assert not [call for call in world.did("run") if call[1][-1] == "migrate"], "no migration without its backup"
        assert report.outcome(Stage.CORE).status is BLOCKED
        assert report.outcome(Stage.COCKPIT).status is BLOCKED
        assert not world.did("spawn")

    def test_a_drifted_schema_is_never_migrated_over(self, world: World) -> None:
        world.drifted = ["0003_changed_after_the_fact"]
        report = world.starter().start()
        assert report.outcome(Stage.SCHEMA).status is FAILED
        assert not [call for call in world.did("run") if call[1][-1] == "migrate"]
        assert not world.did("spawn")

    def test_a_migration_that_fails_stops_the_core_from_starting(self, world: World) -> None:
        world.pending = ["0007_something"]
        world.migrate_ok = False
        report = world.starter().start()
        assert report.outcome(Stage.SCHEMA).status is FAILED
        assert not world.did("spawn")


class TestTheDatabase:
    def test_a_container_that_cannot_be_started_blocks_everything_after_it(self, world: World) -> None:
        world.start_container_ok = False
        report = world.starter().start()
        assert report.outcome(Stage.DATABASE).status is FAILED
        assert statuses(report)[Stage.SCHEMA] is BLOCKED
        assert statuses(report)[Stage.CORE] is BLOCKED
        assert statuses(report)[Stage.COCKPIT] is BLOCKED
        assert not world.did("spawn") and not world.did("run")
        assert not report.ok

    def test_a_database_that_never_becomes_healthy_fails_after_its_timeout(self, world: World) -> None:
        world.db_never_healthy = True
        report = world.starter().start()
        assert report.outcome(Stage.DATABASE).status is FAILED
        assert (world.clock.now() - T0).total_seconds() >= world.config.timeouts.database_s
        assert not world.did("spawn")

    def test_docker_that_does_not_answer_blocks_and_nothing_is_tried(self, world: World) -> None:
        world.docker_up = False
        report = world.starter().start()
        assert report.outcome(Stage.DATABASE).status is BLOCKED
        assert not world.calls

    def test_another_containers_port_blocks_and_that_container_is_not_touched(self, world: World) -> None:
        world.container = None
        world.holders = ["dossier-db-1"]
        report = world.starter().start()
        assert report.outcome(Stage.DATABASE).status is BLOCKED
        assert not world.calls


class TestTheCore:
    def test_a_core_that_dies_at_boot_fails_with_its_log_and_is_forgotten(self, world: World) -> None:
        world.core_dies_at_boot = True
        report = world.starter().start()
        outcome = report.outcome(Stage.CORE)
        assert outcome.status is FAILED
        assert "core-" in outcome.detail, "the message points at the log"
        assert world.registry.load().owned == ()
        assert report.outcome(Stage.COCKPIT).status is BLOCKED
        assert len(world.did("spawn")) == 1

    def test_a_core_that_never_answers_fails_but_stays_recorded_so_that_stop_can_end_it(self, world: World) -> None:
        world.core_never_ready = True
        report = world.starter().start()
        assert report.outcome(Stage.CORE).status is FAILED
        assert [item.component for item in world.registry.load().owned] == [Component.CORE]
        assert report.outcome(Stage.COCKPIT).status is BLOCKED

    def test_a_process_that_cannot_be_spawned_is_a_failure_not_a_crash(self, world: World) -> None:
        world.spawn_fails = True
        report = world.starter().start()
        assert report.outcome(Stage.CORE).status is FAILED
        assert world.registry.load().owned == ()

    def test_a_foreign_process_on_the_core_ports_blocks_it_and_is_not_touched(self, world: World) -> None:
        stranger = world.add_process(900, r'"C:\other\python.exe" -m something_else')
        world.listen(world.config.api_port, stranger.pid)
        report = world.starter().start()
        assert report.outcome(Stage.CORE).status is BLOCKED
        assert report.outcome(Stage.COCKPIT).status is BLOCKED
        assert not world.did("spawn")
        assert world.alive(900)

    @pytest.mark.parametrize("missing", ["has_venv", "has_env_file"])
    def test_a_missing_prerequisite_blocks_the_core_before_anything_is_spawned(
        self, world: World, missing: str
    ) -> None:
        setattr(world, missing, False)
        report = world.starter().start()
        assert report.outcome(Stage.CORE).status is BLOCKED
        assert not world.did("spawn")


class TestTheCockpit:
    def test_a_cockpit_that_never_answers_fails_without_touching_the_rest(self, world: World) -> None:
        world.cockpit_never_ready = True
        report = world.starter().start()
        assert report.outcome(Stage.COCKPIT).status is FAILED
        assert report.outcome(Stage.DATABASE).status is DONE
        assert report.outcome(Stage.CORE).status is DONE
        assert world.core_up
        assert not report.ok

    def test_missing_npm_blocks_the_cockpit_only(self, world: World) -> None:
        world.has_npm = False
        report = world.starter().start()
        assert report.outcome(Stage.COCKPIT).status is BLOCKED
        assert report.outcome(Stage.CORE).status is DONE

    def test_a_foreign_process_on_port_3000_blocks_the_cockpit_and_is_not_touched(self, world: World) -> None:
        stranger = world.add_process(901, r"node C:\Ebrain\jobdom\04_code\node_modules\next\dist\x.js", name="node.exe")
        world.listen(world.config.cockpit_port, stranger.pid)
        report = world.starter().start()
        assert report.outcome(Stage.COCKPIT).status is BLOCKED
        assert report.outcome(Stage.CORE).status is DONE
        assert world.alive(901)
        assert len(world.did("spawn")) == 1


class TestNoSecretIsKept:
    def test_a_secret_in_a_command_output_never_reaches_the_events_or_the_report(self, world: World) -> None:
        clear_secrets()
        register_secret("hunter2hunter2")
        try:
            world.drifted = ["0003_changed"]
            world.status_output_extra = "\npassword=hunter2hunter2"
            report = world.starter().start()
        finally:
            clear_secrets()
        text = json.dumps(report.model_dump(mode="json")) + "".join(
            path.read_text(encoding="utf-8") for path in world.config.events_dir.glob("events-*.jsonl")
        )
        assert "hunter2hunter2" not in text
