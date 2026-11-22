"""What the launcher *sees* (ADR 0038, § 3): who holds a port, and whether they are ours. A listener is **owned** when it descends from a
process the launcher recorded (pid *and* creation time, against the reuse of a pid), **recognized** when its command line carries this
repository's signature, and **foreign** otherwise — a foreign process is reported, never touched, and never taken for a component."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from tests.unit.launcher.support import (
    CORE_CMD,
    NEXT_PATH,
    REPO,
    T0,
    FakeDocker,
    FakeEnvironment,
    FakeHealth,
    FakeProcessTable,
    container,
    core_health,
    listener,
    make_config,
    proc,
)
from trading_os.launcher.model import (
    Component,
    ComponentState,
    Observation,
    OwnedProcess,
    Ownership,
)
from trading_os.launcher.observe import Observer
from trading_os.launcher.registry import ProcessRegistry
from trading_os.shared.time import ManualClock

CONFIG = make_config()
CORE_PROCESS = proc(1668, command_line=CORE_CMD, parent_pid=16780)
COCKPIT_PROCESS = proc(7900, name="node.exe", command_line=f'"C:\\Program Files\\nodejs\\node.exe" {NEXT_PATH}')


def observe(
    *,
    processes: list | None = None,  # type: ignore[type-arg]
    listeners: list | None = None,  # type: ignore[type-arg]
    docker: FakeDocker | None = None,
    health: FakeHealth | None = None,
    environment: FakeEnvironment | None = None,
    registry_path: Path | None = None,
) -> Observation:
    clock = ManualClock(T0)
    full = FakeEnvironment(existing=[CONFIG.venv_python, CONFIG.env_file], tools=["npm"])
    return Observer(
        CONFIG,
        processes=FakeProcessTable(processes or [], listeners or []),
        docker=docker or FakeDocker(container=container()),
        health=health or FakeHealth(),
        environment=environment or full,
        registry=ProcessRegistry(registry_path or Path("does-not-exist/state.json"), clock),
        clock=clock,
    ).observe()


def state_of(observation: Observation, component: Component) -> ComponentState:
    return observation.component(component).state


class TestTheEnvironment:
    def test_the_prerequisites_are_read_without_opening_any_file(self) -> None:
        observation = observe(environment=FakeEnvironment(tools=[]))
        assert observation.environment.venv_python_present is False
        assert observation.environment.env_file_present is False
        assert observation.environment.npm_available is False
        assert observation.environment.docker_available is True

    def test_docker_that_does_not_answer_is_reported_as_unavailable(self) -> None:
        observation = observe(docker=FakeDocker(available=False))
        assert observation.environment.docker_available is False
        assert state_of(observation, Component.DATABASE) is ComponentState.UNAVAILABLE


class TestNothingRunning:
    def test_every_component_is_absent(self) -> None:
        observation = observe(docker=FakeDocker(container=None))
        assert [c.state for c in observation.components] == [ComponentState.ABSENT] * 3
        assert all(c.ownership is Ownership.NONE for c in observation.components)


class TestTheCore:
    def healthy(self, **kw: object) -> Observation:
        return observe(
            processes=[CORE_PROCESS],
            listeners=[listener(8000, 1668), listener(9765, 1668)],
            health=FakeHealth(core=core_health(**kw)),
        )

    def test_a_core_carrying_the_signature_and_answering_is_recognized_and_healthy(self) -> None:
        core = self.healthy().component(Component.CORE)
        assert core.state is ComponentState.HEALTHY
        assert core.ownership is Ownership.RECOGNIZED
        assert core.pid == 1668

    def test_it_asks_the_health_of_the_configured_address(self) -> None:
        health = FakeHealth(core=core_health())
        observe(processes=[CORE_PROCESS], listeners=[listener(8000, 1668), listener(9765, 1668)], health=health)
        assert "http://127.0.0.1:8000/api/system/health" in health.asked

    def test_the_health_the_core_reported_is_kept_on_the_observation_for_the_diagnosis(self) -> None:
        observation = self.healthy(agents_connected=1)
        assert observation.core_health is not None
        assert observation.core_health.agents_connected == 1
        assert observation.core_health.version == "0.2.0"

    def test_the_health_is_kept_even_when_the_core_is_judged_unhealthy(self) -> None:
        observation = self.healthy(status="critical")
        assert state_of(observation, Component.CORE) is ComponentState.UNHEALTHY
        assert observation.core_health is not None
        assert observation.core_health.status == "critical"

    def test_without_an_answer_or_without_a_core_there_is_no_health_on_the_observation(self) -> None:
        silent = observe(processes=[CORE_PROCESS], listeners=[listener(8000, 1668), listener(9765, 1668)])
        assert silent.core_health is None
        assert observe().core_health is None

    def test_a_core_that_does_not_answer_is_unhealthy_not_absent(self) -> None:
        observation = observe(processes=[CORE_PROCESS], listeners=[listener(8000, 1668), listener(9765, 1668)])
        assert state_of(observation, Component.CORE) is ComponentState.UNHEALTHY

    def test_a_database_down_or_a_critical_status_is_unhealthy(self) -> None:
        assert state_of(self.healthy(database_up=False), Component.CORE) is ComponentState.UNHEALTHY
        assert state_of(self.healthy(status="critical"), Component.CORE) is ComponentState.UNHEALTHY

    def test_a_warning_status_does_not_make_the_process_unhealthy(self) -> None:
        """The launcher answers « is it up »; an MT5 incident is the readiness report's business."""
        assert state_of(self.healthy(status="medium", findings=2), Component.CORE) is ComponentState.HEALTHY

    def test_a_core_without_its_agent_link_listening_is_unhealthy(self) -> None:
        observation = observe(
            processes=[CORE_PROCESS], listeners=[listener(8000, 1668)], health=FakeHealth(core=core_health())
        )
        core = observation.component(Component.CORE)
        assert core.state is ComponentState.UNHEALTHY
        assert "9765" in core.detail

    def test_a_foreign_process_on_the_api_port_is_foreign_even_if_it_answers_the_health_check(self) -> None:
        other = proc(555, name="python.exe", command_line=r'"C:\other\project\python.exe" -m some_other_app')
        observation = observe(processes=[other], listeners=[listener(8000, 555)], health=FakeHealth(core=core_health()))
        core = observation.component(Component.CORE)
        assert core.state is ComponentState.FOREIGN
        assert core.ownership is Ownership.FOREIGN
        assert core.pid == 555

    def test_a_foreign_process_on_the_agent_link_port_is_foreign(self) -> None:
        other = proc(556, command_line=r'"C:\other\project\python.exe" -m something')
        observation = observe(
            processes=[CORE_PROCESS, other],
            listeners=[listener(8000, 1668), listener(9765, 556)],
            health=FakeHealth(core=core_health()),
        )
        assert state_of(observation, Component.CORE) is ComponentState.FOREIGN

    def test_the_signature_includes_this_repository_so_another_checkout_is_foreign(self) -> None:
        other_checkout = proc(
            777, command_line=r'"C:\Somewhere\Else\04_code\python\.venv\Scripts\python.exe" -m trading_os serve'
        )
        observation = observe(
            processes=[other_checkout],
            listeners=[listener(8000, 777), listener(9765, 777)],
            health=FakeHealth(core=core_health()),
        )
        assert state_of(observation, Component.CORE) is ComponentState.FOREIGN

    def test_the_repository_marker_is_found_whatever_the_case_or_the_separators(self) -> None:
        shouting = proc(1668, command_line=CORE_CMD.upper().replace("\\", "/"))
        observation = observe(
            processes=[shouting],
            listeners=[listener(8000, 1668), listener(9765, 1668)],
            health=FakeHealth(core=core_health()),
        )
        assert observation.component(Component.CORE).ownership is Ownership.RECOGNIZED


class TestTheCockpit:
    def test_a_next_server_of_this_repository_answering_200_is_healthy(self) -> None:
        observation = observe(
            processes=[COCKPIT_PROCESS], listeners=[listener(3000, 7900)], health=FakeHealth(cockpit_status=200)
        )
        cockpit = observation.component(Component.COCKPIT)
        assert cockpit.state is ComponentState.HEALTHY
        assert cockpit.ownership is Ownership.RECOGNIZED

    def test_another_projects_next_server_on_port_3000_is_foreign(self) -> None:
        """Audit D3: start.ps1 takes anything on 3000 for the cockpit. Another project's Next.js server is not ours."""
        foreign = proc(
            17456,
            name="node.exe",
            command_line=r'"C:\Program Files\nodejs\node.exe" C:\Ebrain\jobdom\04_code\node_modules\next\dist\server\lib\start-server.js',
        )
        observation = observe(
            processes=[foreign], listeners=[listener(3000, 17456)], health=FakeHealth(cockpit_status=200)
        )
        cockpit = observation.component(Component.COCKPIT)
        assert cockpit.state is ComponentState.FOREIGN
        assert cockpit.pid == 17456

    def test_a_cockpit_that_listens_but_answers_an_error_is_unhealthy(self) -> None:
        observation = observe(
            processes=[COCKPIT_PROCESS], listeners=[listener(3000, 7900)], health=FakeHealth(cockpit_status=500)
        )
        assert state_of(observation, Component.COCKPIT) is ComponentState.UNHEALTHY

    def test_a_redirect_counts_as_an_answer(self) -> None:
        observation = observe(
            processes=[COCKPIT_PROCESS], listeners=[listener(3000, 7900)], health=FakeHealth(cockpit_status=307)
        )
        assert state_of(observation, Component.COCKPIT) is ComponentState.HEALTHY

    def test_a_cockpit_listening_on_every_interface_is_reported_with_a_warning(self) -> None:
        observation = observe(
            processes=[COCKPIT_PROCESS],
            listeners=[listener(3000, 7900, address="0.0.0.0")],
            health=FakeHealth(cockpit_status=200),
        )
        cockpit = observation.component(Component.COCKPIT)
        assert cockpit.state is ComponentState.HEALTHY
        assert cockpit.warnings


class TestTheDatabase:
    def test_a_healthy_container_publishing_the_expected_port(self) -> None:
        db = observe(docker=FakeDocker(container=container())).component(Component.DATABASE)
        assert db.state is ComponentState.HEALTHY
        assert db.ownership is Ownership.RECOGNIZED

    def test_a_starting_container(self) -> None:
        observation = observe(docker=FakeDocker(container=container(health="starting")))
        assert state_of(observation, Component.DATABASE) is ComponentState.STARTING

    def test_an_unhealthy_container(self) -> None:
        observation = observe(docker=FakeDocker(container=container(health="unhealthy")))
        assert state_of(observation, Component.DATABASE) is ComponentState.UNHEALTHY

    def test_a_stopped_container_can_be_started(self) -> None:
        observation = observe(docker=FakeDocker(container=container(status="exited", health=None)))
        assert state_of(observation, Component.DATABASE) is ComponentState.ABSENT

    def test_a_container_that_is_not_publishing_the_expected_port_is_unhealthy(self) -> None:
        observation = observe(docker=FakeDocker(container=container(ports=(5434,))))
        db = observation.component(Component.DATABASE)
        assert db.state is ComponentState.UNHEALTHY
        assert "5434" in db.detail

    def test_another_container_holding_the_port_is_foreign(self) -> None:
        observation = observe(docker=FakeDocker(container=None, holders=["dossier-db-1"]))
        db = observation.component(Component.DATABASE)
        assert db.state is ComponentState.FOREIGN
        assert "dossier-db-1" in db.detail

    def test_our_own_container_holding_the_port_is_not_foreign(self) -> None:
        observation = observe(docker=FakeDocker(container=container(), holders=["tradingos-timescaledb"]))
        assert state_of(observation, Component.DATABASE) is ComponentState.HEALTHY

    def test_a_process_on_the_port_while_our_container_is_stopped_is_foreign(self) -> None:
        observation = observe(
            processes=[proc(900, name="postgres.exe", command_line="postgres.exe -D data")],
            listeners=[listener(5433, 900)],
            docker=FakeDocker(container=None),
        )
        assert state_of(observation, Component.DATABASE) is ComponentState.FOREIGN


class TestOwnership:
    def owned(self, pid: int, created_at=T0) -> OwnedProcess:  # type: ignore[no-untyped-def]
        return OwnedProcess(
            component=Component.CORE,
            pid=pid,
            created_at=created_at,
            command_line="launcher-started core",
            started_at=T0,
            working_directory=str(REPO / "python"),
            log_path=None,
            correlation_id="abc123",
        )

    def registry_with(self, tmp_path: Path, *entries: OwnedProcess) -> Path:
        path = tmp_path / "state.json"
        registry = ProcessRegistry(path, ManualClock(T0))
        for entry in entries:
            registry.record(entry)
        return path

    def test_a_listener_descending_from_a_process_the_launcher_started_is_owned(self, tmp_path: Path) -> None:
        launcher_python = proc(16780, command_line="python launcher", parent_pid=1)
        real_interpreter = proc(1668, command_line="python something unrelated", parent_pid=16780)
        observation = observe(
            processes=[launcher_python, real_interpreter],
            listeners=[listener(8000, 1668), listener(9765, 1668)],
            health=FakeHealth(core=core_health()),
            registry_path=self.registry_with(tmp_path, self.owned(16780)),
        )
        core = observation.component(Component.CORE)
        assert core.ownership is Ownership.OWNED
        assert core.state is ComponentState.HEALTHY

    def test_a_recycled_pid_is_not_ours(self, tmp_path: Path) -> None:
        """The recorded process died and Windows gave its pid to another: the creation time differs, so it is no longer owned."""
        reused = proc(16780, command_line="python something else", created_at=T0 + timedelta(hours=3))
        listening = proc(1668, command_line="python something unrelated", parent_pid=16780)
        observation = observe(
            processes=[reused, listening],
            listeners=[listener(8000, 1668), listener(9765, 1668)],
            health=FakeHealth(core=core_health()),
            registry_path=self.registry_with(tmp_path, self.owned(16780)),
        )
        core = observation.component(Component.CORE)
        assert core.ownership is Ownership.FOREIGN
        assert core.state is ComponentState.FOREIGN

    def test_a_dead_recorded_process_owns_nothing(self, tmp_path: Path) -> None:
        observation = observe(registry_path=self.registry_with(tmp_path, self.owned(16780)), docker=FakeDocker())
        assert observation.owned == ()
        assert state_of(observation, Component.CORE) is ComponentState.ABSENT

    def test_a_corrupt_registry_owns_nothing_and_says_so(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        path.write_text("{ not json", encoding="utf-8")
        observation = observe(registry_path=path)
        assert observation.owned == ()
        assert observation.registry_problem

    def test_a_process_of_another_component_does_not_make_the_cockpit_ours(self, tmp_path: Path) -> None:
        launcher_core = proc(16780, command_line="python launcher", parent_pid=1)
        stranger = proc(7900, name="node.exe", command_line="node somewhere", parent_pid=16780)
        observation = observe(
            processes=[launcher_core, stranger],
            listeners=[listener(3000, 7900)],
            health=FakeHealth(cockpit_status=200),
            registry_path=self.registry_with(tmp_path, self.owned(16780)),
        )
        assert observation.component(Component.COCKPIT).ownership is Ownership.FOREIGN

    def test_a_parent_loop_does_not_hang_the_observation(self) -> None:
        a = proc(10, command_line="x", parent_pid=11)
        b = proc(11, command_line="y", parent_pid=10)
        observation = observe(processes=[a, b], listeners=[listener(3000, 10)], health=FakeHealth(cockpit_status=200))
        assert state_of(observation, Component.COCKPIT) is ComponentState.FOREIGN
