"""Stopping (ADR 0038, § 5): **only what the registry says the launcher started**, proven by pid and creation time — never a process because it
is on a port or carries a name. Order: cockpit, core (asked politely first), then the database if the launcher started it. MetaTrader and
its agent are not touched, no position is closed, no order is sent."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.launcher.support import T0
from tests.unit.launcher.world import World
from trading_os.launcher.events import EventType
from trading_os.launcher.model import (
    Component,
    OwnedContainer,
    OwnedProcess,
    StopStatus,
)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def own(world: World, component: Component, pid: int) -> None:
    process = next(item for item in world.table.processes() if item.pid == pid)
    world.registry.record(
        OwnedProcess(
            component=component,
            pid=pid,
            created_at=process.created_at or T0,
            command_line=process.command_line,
            started_at=T0,
            working_directory=None,
            log_path=None,
            correlation_id="earlier-run",
        )
    )


def own_everything(world: World, *, container: bool = True) -> None:
    world.run_everything()
    own(world, Component.CORE, world.core_launcher_pid)
    own(world, Component.COCKPIT, world.cockpit_parent_pid)
    if container:
        world.registry.record_container(
            OwnedContainer(name=world.config.container_name, started_at=T0, correlation_id="earlier-run")
        )


def stopped_pids(world: World) -> set[int]:
    return {int(call[1]) for call in world.calls if str(call[0]).startswith("stop.")}  # type: ignore[call-overload]


class TestWhatTheLauncherStarted:
    def test_everything_it_started_is_stopped_in_reverse_order(self, world: World) -> None:
        own_everything(world)
        report = world.stopper().stop()
        assert report.ok
        assert [report.outcome(c).status for c in (Component.COCKPIT, Component.CORE, Component.DATABASE)] == [
            StopStatus.STOPPED
        ] * 3
        kinds = [str(call[0]) for call in world.calls]
        assert kinds.index("stop.terminate") < kinds.index("stop.request") < kinds.index("docker.stop")
        assert not world.core_up and not world.cockpit_up
        assert world.container is not None and world.container.status == "exited"

    def test_the_core_is_asked_politely_and_not_killed_when_it_obeys(self, world: World) -> None:
        own_everything(world)
        world.stopper().stop()
        assert world.did("stop.request") == [("stop.request", world.core_launcher_pid)]
        assert (("stop.terminate", world.core_launcher_pid)) not in world.calls

    def test_a_core_that_ignores_the_request_is_ended_after_the_grace_period(self, world: World) -> None:
        own_everything(world)
        world.graceful_stop_works = False
        report = world.stopper().stop()
        assert report.outcome(Component.CORE).status is StopStatus.STOPPED
        assert ("stop.terminate", world.core_launcher_pid) in world.calls
        assert (world.clock.now() - T0).total_seconds() >= world.config.timeouts.stop_grace_s

    def test_a_process_that_cannot_be_ended_is_a_failure_that_says_so(self, world: World) -> None:
        own_everything(world, container=False)
        world.kill_fails = True
        report = world.stopper().stop()
        assert report.outcome(Component.COCKPIT).status is StopStatus.FAILED
        assert not report.ok

    def test_the_registry_forgets_what_was_stopped_and_the_events_say_so(self, world: World) -> None:
        own_everything(world)
        world.stopper().stop()
        snapshot = world.registry.load()
        assert snapshot.owned == () and snapshot.containers == ()
        stopped = [event for event in world.events.read() if event.type is EventType.LAUNCHER_PROCESS_STOPPED]
        assert len(stopped) == 3
        assert {event.correlation_id for event in stopped} == {"run-2"}

    def test_only_owned_pids_are_ever_handed_to_the_controller(self, world: World) -> None:
        own_everything(world)
        stranger = world.add_process(900, "node unrelated.js", name="node.exe")
        terminal = world.add_process(901, r'"C:\Program Files\MetaTrader 5\terminal64.exe"', name="terminal64.exe")
        world.stopper().stop()
        assert stopped_pids(world) <= {world.core_launcher_pid, world.cockpit_parent_pid}
        assert world.alive(stranger.pid) and world.alive(terminal.pid), "MetaTrader and strangers are never touched"


class TestWhatTheLauncherDidNotStart:
    def test_a_recognized_application_started_by_hand_is_reported_and_left_running(self, world: World) -> None:
        world.run_everything()
        report = world.stopper().stop()
        assert report.outcome(Component.CORE).status is StopStatus.NOT_OURS
        assert report.outcome(Component.COCKPIT).status is StopStatus.NOT_OURS
        assert "adopt" in report.outcome(Component.CORE).detail
        assert not [call for call in world.calls if str(call[0]).startswith(("stop.", "docker.stop"))]
        assert world.core_up and world.cockpit_up

    def test_a_foreign_process_is_never_touched(self, world: World) -> None:
        stranger = world.add_process(900, r'"C:\other\python.exe" -m something_else')
        world.listen(world.config.api_port, stranger.pid)
        report = world.stopper().stop()
        assert report.outcome(Component.CORE).status is StopStatus.NOT_OURS
        assert world.alive(900)
        assert not world.calls

    def test_a_recycled_pid_is_not_ended_and_the_stale_entry_is_forgotten(self, world: World) -> None:
        own_everything(world, container=False)
        old = next(item for item in world.table.processes() if item.pid == world.core_launcher_pid)
        world.table._processes[:] = [item for item in world.table._processes if item.pid != old.pid]
        impostor = world.add_process(old.pid, "something completely different")
        world.clock.advance(hours=3)
        impostor_later = impostor.model_copy(update={"created_at": world.clock.now()})
        world.table._processes[:] = [
            impostor_later if item.pid == impostor.pid else item for item in world.table._processes
        ]
        world.stopper().stop()
        assert old.pid not in stopped_pids(world)
        assert world.alive(old.pid)
        assert Component.CORE not in {item.component for item in world.registry.load().owned}

    def test_nothing_running_is_not_an_error(self, world: World) -> None:
        report = world.stopper().stop()
        assert report.ok
        assert {item.status for item in report.outcomes} == {StopStatus.NOT_RUNNING}


class TestTheDatabase:
    def test_a_container_the_launcher_did_not_start_is_not_stopped(self, world: World) -> None:
        own_everything(world, container=False)
        report = world.stopper().stop()
        assert report.outcome(Component.DATABASE).status is StopStatus.NOT_OURS
        assert not world.did("docker.stop")

    def test_include_database_stops_that_container_and_only_that_one(self, world: World) -> None:
        own_everything(world, container=False)
        world.holders = ["dossier-db-1"]
        report = world.stopper().stop(include_database=True)
        assert report.outcome(Component.DATABASE).status is StopStatus.STOPPED
        assert world.did("docker.stop") == [("docker.stop", world.config.container_name)]


class TestDryRun:
    def test_it_says_what_would_be_stopped_and_stops_nothing(self, world: World) -> None:
        own_everything(world)
        report = world.stopper().stop(dry_run=True)
        assert [item.status for item in report.outcomes] == [StopStatus.WOULD_STOP] * 3
        assert not [call for call in world.calls if str(call[0]).startswith(("stop.", "docker."))]
        assert len(world.registry.load().owned) == 2
        assert world.core_up and world.cockpit_up


class TestAfterTheCoreIsGone:
    def test_workers_left_behind_are_reported_and_not_touched(self, world: World) -> None:
        own_everything(world)
        worker = world.add_process(
            950, f'"{world.config.venv_python}" -m trading_os.infrastructure.mt5.worker --backend real', parent=1
        )
        report = world.stopper().stop()
        assert any("950" in warning for warning in report.warnings)
        assert world.alive(worker.pid)
        assert 950 not in stopped_pids(world)
