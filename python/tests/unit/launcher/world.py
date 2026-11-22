"""A simulated machine for the start and stop tests (ADR 0038, I2): processes, ports, one container, the commands the launcher runs, and a clock
that only moves when the launcher sleeps. Components become healthy after a delay; everything the launcher does to the world is written to
``calls``, so a test can say what was — and what was **not** — done.

Nothing here touches the real machine: the registry and the events are real files, but under ``tmp_path``.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

from tests.unit.launcher.support import T0, FakeProcessTable
from trading_os.launcher.cli import Runtime
from trading_os.launcher.events import EventLog
from trading_os.launcher.model import (
    ContainerInfo,
    CoreHealth,
    LauncherConfig,
    Listener,
    ProcessInfo,
    Timeouts,
)
from trading_os.launcher.observe import Observer
from trading_os.launcher.ports import CommandResult, SpawnError
from trading_os.launcher.registry import ProcessRegistry
from trading_os.launcher.starter import Starter
from trading_os.launcher.stopper import Stopper
from trading_os.shared.time import ManualClock

FAST = Timeouts(
    database_s=20,
    core_s=20,
    cockpit_s=20,
    process_visible_s=2,
    migrate_s=20,
    stop_grace_s=10,
    stop_confirm_s=5,
    poll_s=1,
)


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.clock = ManualClock(T0)
        self.config = LauncherConfig(repo_root=tmp_path / "04_code", timeouts=FAST)
        self.table = FakeProcessTable()
        self.container: ContainerInfo | None = None
        self.docker_up = True
        self.holders: list[str] = []
        self.has_venv = True
        self.has_env_file = True
        self.has_npm = True
        self.core_up = False
        self.cockpit_up = False
        # how the world behaves
        self.db_boot_s = 3.0
        self.core_boot_s = 4.0
        self.cockpit_boot_s = 6.0
        self.db_never_healthy = False
        self.core_dies_at_boot = False
        self.core_never_ready = False
        self.cockpit_never_ready = False
        self.start_container_ok = True
        self.compose_ok = True
        self.dump_ok = True
        self.migrate_ok = True
        self.spawn_fails = False
        self.graceful_stop_works = True
        self.kill_fails = False
        self.after_docker_start: Callable[[], None] | None = None
        self.pending: list[str] = []
        self.drifted: list[str] = []
        self.status_output_extra = ""
        self.calls: list[tuple[object, ...]] = []
        self._due: list[tuple[datetime, Callable[[], None]]] = []
        self._pid = 5000
        self.registry = ProcessRegistry(self.config.registry_path, self.clock)
        self.events = EventLog(self.config.events_dir, self.clock)

    # ------------------------------------------------------------------------------------------------ time

    def schedule(self, delay: float, action: Callable[[], None]) -> None:
        from datetime import timedelta

        self._due.append((self.clock.now() + timedelta(seconds=delay), action))

    def advance(self, seconds: float) -> None:
        from datetime import timedelta

        target = self.clock.now() + timedelta(seconds=seconds)
        while True:
            due = sorted((item for item in self._due if item[0] <= target), key=lambda item: item[0])
            if not due:
                break
            when, action = due[0]
            self._due.remove(due[0])
            self.clock.set(when)
            action()
        self.clock.set(target)

    def sleep(self, seconds: float) -> None:  # the Sleeper port
        self.advance(seconds)

    # ------------------------------------------------------------------------------------------------ building blocks

    def new_pid(self) -> int:
        self._pid += 1
        return self._pid

    def add_process(self, pid: int, command_line: str, *, parent: int = 1, name: str = "python.exe") -> ProcessInfo:
        item = ProcessInfo(
            pid=pid, parent_pid=parent, name=name, command_line=command_line, created_at=self.clock.now()
        )
        self.table._processes.append(item)
        return item

    def listen(self, port: int, pid: int, address: str = "127.0.0.1") -> None:
        self.table._listeners.append(Listener(address=address, port=port, pid=pid))

    def alive(self, pid: int) -> bool:
        return any(item.pid == pid for item in self.table._processes)

    def remove_tree(self, pid: int) -> None:
        doomed = {pid}
        grew = True
        while grew:
            grew = False
            for item in self.table._processes:
                if item.parent_pid in doomed and item.pid not in doomed:
                    doomed.add(item.pid)
                    grew = True
        gone_ports = {item.port for item in self.table._listeners if item.pid in doomed}
        self.table._processes[:] = [item for item in self.table._processes if item.pid not in doomed]
        self.table._listeners[:] = [item for item in self.table._listeners if item.pid not in doomed]
        if self.config.api_port in gone_ports:
            self.core_up = False
        if self.config.cockpit_port in gone_ports:
            self.cockpit_up = False

    def run_everything(self, *, owned_by_launcher: bool = False) -> None:
        """Put the whole application up (as if it had been started by hand) — the database healthy, the core and the cockpit answering."""
        self.container = ContainerInfo(
            name=self.config.container_name, status="running", health="healthy", host_ports=(self.config.db_port,)
        )
        core_launcher = self.add_process(
            self.new_pid(), subprocess.list2cmdline([str(self.config.venv_python), "-m", "trading_os", "serve"])
        )
        core = self.add_process(self.new_pid(), core_launcher.command_line, parent=core_launcher.pid)
        self.listen(self.config.api_port, core.pid)
        self.listen(self.config.ea_link_port, core.pid)
        self.core_up = True
        node = f'node "{self.config.repo_root}\\node_modules\\next\\dist\\server\\lib\\start-server.js"'
        cockpit_parent = self.add_process(self.new_pid(), "cmd /c next dev", name="cmd.exe")
        cockpit = self.add_process(self.new_pid(), node, parent=cockpit_parent.pid, name="node.exe")
        self.listen(self.config.cockpit_port, cockpit.pid)
        self.cockpit_up = True
        self.core_pid, self.core_launcher_pid = core.pid, core_launcher.pid
        self.cockpit_pid, self.cockpit_parent_pid = cockpit.pid, cockpit_parent.pid

    # ------------------------------------------------------------------------------------------------ the ports

    @property
    def processes(self) -> FakeProcessTable:
        return self.table

    @property
    def docker(self) -> _Docker:
        return _Docker(self)

    @property
    def actions(self) -> _Actions:
        return _Actions(self)

    @property
    def health(self) -> _Health:
        return _Health(self)

    @property
    def environment(self) -> _Environment:
        return _Environment(self)

    @property
    def runner(self) -> _Runner:
        return _Runner(self)

    @property
    def spawner(self) -> _Spawner:
        return _Spawner(self)

    @property
    def controller(self) -> _Controller:
        return _Controller(self)

    def observer(self) -> Observer:
        return Observer(
            self.config,
            processes=self.table,
            docker=self.docker,
            health=self.health,
            environment=self.environment,
            registry=self.registry,
            clock=self.clock,
        )

    def starter(self, correlation_id: str = "run-1") -> Starter:
        return Starter(
            self.config,
            observer=self.observer(),
            docker=self.docker,
            actions=self.actions,
            runner=self.runner,
            spawner=self.spawner,
            processes=self.table,
            environment=self.environment,
            registry=self.registry,
            events=self.events,
            clock=self.clock,
            sleeper=self,
            correlation_id=correlation_id,
        )

    def stopper(self, correlation_id: str = "run-2") -> Stopper:
        return Stopper(
            self.config,
            observer=self.observer(),
            docker=self.docker,
            actions=self.actions,
            controller=self.controller,
            processes=self.table,
            registry=self.registry,
            events=self.events,
            clock=self.clock,
            sleeper=self,
            correlation_id=correlation_id,
        )

    def runtime(self) -> Runtime:
        """The same machine, wired the way ``launcher.cli`` wires the real one (the launcher itself is process 777)."""
        self.add_process(777, "python -m trading_os launcher")
        return Runtime(
            observer=self.observer(),
            docker=self.docker,
            actions=self.actions,
            runner=self.runner,
            spawner=self.spawner,
            controller=self.controller,
            processes=self.table,
            environment=self.environment,
            registry=self.registry,
            events=self.events,
            clock=self.clock,
            sleeper=self,
            own_pid=777,
        )

    def did(self, kind: str) -> list[tuple[object, ...]]:
        return [call for call in self.calls if call[0] == kind]


class _Docker:
    def __init__(self, world: World) -> None:
        self._w = world

    def available(self) -> bool:
        return self._w.docker_up

    def container(self, name: str) -> ContainerInfo | None:
        return self._w.container

    def port_holders(self, port: int) -> list[str]:
        return list(self._w.holders)


class _Actions:
    def __init__(self, world: World) -> None:
        self._w = world

    def _boot_container(self) -> None:
        w = self._w
        w.container = ContainerInfo(
            name=w.config.container_name, status="running", health="starting", host_ports=(w.config.db_port,)
        )
        if not w.db_never_healthy:
            w.schedule(w.db_boot_s, self._healthy)

    def _healthy(self) -> None:
        if self._w.container is not None and self._w.container.status == "running":
            self._w.container = self._w.container.model_copy(update={"health": "healthy"})

    def start_container(self, name: str) -> bool:
        self._w.calls.append(("docker.start", name))
        if not self._w.start_container_ok or self._w.container is None:
            return False
        self._boot_container()
        if self._w.after_docker_start is not None:
            self._w.after_docker_start()
        return True

    def create_database(self, repo_root: Path) -> bool:
        self._w.calls.append(("docker.compose_up", str(repo_root)))
        if not self._w.compose_ok:
            return False
        self._boot_container()
        return True

    def stop_container(self, name: str) -> bool:
        self._w.calls.append(("docker.stop", name))
        if self._w.container is not None:
            self._w.container = self._w.container.model_copy(update={"status": "exited", "health": None})
        return True

    def dump_database(self, container: str, destination: Path) -> bool:
        self._w.calls.append(("docker.dump", container, str(destination)))
        if self._w.dump_ok:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"dump")
        return self._w.dump_ok


class _Health:
    def __init__(self, world: World) -> None:
        self._w = world

    def core_health(self, url: str) -> CoreHealth | None:
        if not self._w.core_up:
            return None
        return CoreHealth(status="ok", version="0.2.0", database_up=True, findings=0, started_at=T0)

    def http_status(self, url: str) -> int | None:
        return 200 if self._w.cockpit_up else None


class _Environment:
    def __init__(self, world: World) -> None:
        self._w = world

    def path_exists(self, path: Path) -> bool:
        if path == self._w.config.venv_python:
            return self._w.has_venv
        if path == self._w.config.env_file:
            return self._w.has_env_file
        return path.exists()

    def which(self, name: str) -> str | None:
        return "C:/tools/npm.cmd" if name == "npm" and self._w.has_npm else None


class _Runner:
    def __init__(self, world: World) -> None:
        self._w = world

    def run(self, args: Sequence[str], *, timeout: float, cwd: Path | None = None) -> CommandResult:
        w = self._w
        w.calls.append(("run", tuple(args), str(cwd) if cwd is not None else None))
        tail = tuple(args[-2:])
        if tail == ("db", "status"):
            lines = [f"{name:<30} applied" for name in ("0001_baseline", "0002_core")]
            lines += [f"{name:<30} pending" for name in w.pending]
            lines += [f"{name:<30} DRIFTED" for name in w.drifted]
            return CommandResult(1 if w.drifted else 0, "\n".join(lines) + w.status_output_extra, "")
        if tail == ("db", "migrate"):
            if w.migrate_ok:
                w.pending.clear()
                return CommandResult(0, "applied", "")
            return CommandResult(1, "", "migration failed")
        return CommandResult(0, "", "")


class _Spawner:
    def __init__(self, world: World) -> None:
        self._w = world

    def spawn(self, args: Sequence[str], *, cwd: Path, log_path: Path) -> int:
        w = self._w
        w.calls.append(("spawn", tuple(args), str(cwd), str(log_path)))
        if w.spawn_fails:
            raise SpawnError("cannot start")
        pid = w.new_pid()
        command = subprocess.list2cmdline(list(args))
        w.add_process(pid, command, name=Path(args[0]).name)
        if "serve" in args:
            self._core(pid, command)
        else:
            self._cockpit(pid)
        return pid

    def _core(self, parent: int, command: str) -> None:
        w = self._w
        if w.core_dies_at_boot:
            w.schedule(1.0, lambda: w.remove_tree(parent))
            return
        if w.core_never_ready:
            return

        def ready() -> None:
            child = w.add_process(w.new_pid(), command, parent=parent)
            w.listen(w.config.api_port, child.pid)
            w.listen(w.config.ea_link_port, child.pid)
            w.core_up = True

        w.schedule(w.core_boot_s, ready)

    def _cockpit(self, parent: int) -> None:
        w = self._w
        if w.cockpit_never_ready:
            return

        def ready() -> None:
            node = f'node "{w.config.repo_root}\\node_modules\\next\\dist\\server\\lib\\start-server.js"'
            child = w.add_process(w.new_pid(), node, parent=parent, name="node.exe")
            w.listen(w.config.cockpit_port, child.pid)
            w.cockpit_up = True

        w.schedule(w.cockpit_boot_s, ready)


class _Controller:
    def __init__(self, world: World) -> None:
        self._w = world

    def request_stop(self, pid: int) -> bool:
        w = self._w
        w.calls.append(("stop.request", pid))
        if w.graceful_stop_works:
            w.schedule(1.0, lambda: w.remove_tree(pid))
        return True

    def terminate_tree(self, pid: int) -> bool:
        self._w.calls.append(("stop.terminate", pid))
        if self._w.kill_fails:
            return False
        self._w.remove_tree(pid)
        return True
