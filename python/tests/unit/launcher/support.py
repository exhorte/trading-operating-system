"""Fakes and builders for the launcher tests (ADR 0038). Nothing here touches the machine: no process, no Docker, no port, no file
outside ``tmp_path``. The launcher's rule is that every outside effect goes through a port, and these are the test side of the ports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from trading_os.launcher.model import (
    Component,
    ComponentObservation,
    ComponentState,
    ContainerInfo,
    CoreHealth,
    EnvironmentFacts,
    LauncherConfig,
    Listener,
    Observation,
    Ownership,
    ProcessInfo,
)

T0 = datetime(2026, 11, 6, 15, 30, 0, tzinfo=UTC)
REPO = Path("C:/Ebrain/trading/04_code")
CORE_CMD = f'"{REPO}\\python\\.venv\\Scripts\\python.exe" -m trading_os serve'
NEXT_PATH = f"{REPO}\\node_modules\\next\\dist\\server\\lib\\start-server.js"


def make_config(repo_root: Path = REPO) -> LauncherConfig:
    return LauncherConfig(repo_root=repo_root)


def proc(
    pid: int,
    *,
    name: str = "python.exe",
    command_line: str = "",
    parent_pid: int = 0,
    created_at: datetime | None = T0,
    executable: str | None = None,
) -> ProcessInfo:
    return ProcessInfo(
        pid=pid,
        parent_pid=parent_pid,
        name=name,
        executable=executable,
        command_line=command_line,
        created_at=created_at,
    )


def listener(port: int, pid: int, address: str = "127.0.0.1") -> Listener:
    return Listener(address=address, port=port, pid=pid)


def core_health(**changes: object) -> CoreHealth:
    base: dict[str, object] = {"status": "ok", "version": "0.2.0", "database_up": True, "findings": 0, "started_at": T0}
    base.update(changes)
    return CoreHealth(**base)  # type: ignore[arg-type]


def container(
    *, status: str = "running", health: str | None = "healthy", ports: Sequence[int] = (5433,)
) -> ContainerInfo:
    return ContainerInfo(name="tradingos-timescaledb", status=status, health=health, host_ports=tuple(ports))


def facts(*, docker: bool = True, venv: bool = True, env_file: bool = True, npm: bool = True) -> EnvironmentFacts:
    return EnvironmentFacts(
        docker_available=docker, venv_python_present=venv, env_file_present=env_file, npm_available=npm
    )


def obs(
    *,
    database: ComponentState = ComponentState.HEALTHY,
    core: ComponentState = ComponentState.HEALTHY,
    cockpit: ComponentState = ComponentState.HEALTHY,
    environment: EnvironmentFacts | None = None,
    core_health: CoreHealth | None = None,
    registry_problem: str | None = None,
    ownerships: Mapping[Component, Ownership] | None = None,
    warnings: Mapping[Component, tuple[str, ...]] | None = None,
    details: Mapping[Component, str] | None = None,
) -> Observation:
    """An observation with the three components in the given states (ownership follows the state unless ``ownerships`` says otherwise)."""

    def of(component: Component, state: ComponentState) -> ComponentObservation:
        ownership = {
            ComponentState.FOREIGN: Ownership.FOREIGN,
            ComponentState.ABSENT: Ownership.NONE,
            ComponentState.UNAVAILABLE: Ownership.NONE,
        }.get(state, Ownership.RECOGNIZED)
        return ComponentObservation(
            component=component,
            state=state,
            ownership=(ownerships or {}).get(component, ownership),
            warnings=(warnings or {}).get(component, ()),
            detail=(details or {}).get(component, ""),
        )

    return Observation(
        observed_at=T0,
        environment=environment or facts(),
        components=(
            of(Component.DATABASE, database),
            of(Component.CORE, core),
            of(Component.COCKPIT, cockpit),
        ),
        core_health=core_health,
        registry_problem=registry_problem,
    )


# ------------------------------------------------------------------------------------------------------------ the ports


class FakeProcessTable:
    def __init__(self, processes: Iterable[ProcessInfo] = (), listeners: Iterable[Listener] = ()) -> None:
        self._processes = list(processes)
        self._listeners = list(listeners)

    def processes(self) -> list[ProcessInfo]:
        return list(self._processes)

    def listeners(self, ports: Sequence[int]) -> list[Listener]:
        return [item for item in self._listeners if item.port in ports]


class FakeDocker:
    def __init__(
        self,
        *,
        available: bool = True,
        container: ContainerInfo | None = None,
        holders: Sequence[str] = (),
    ) -> None:
        self._available = available
        self._container = container
        self._holders = list(holders)

    def available(self) -> bool:
        return self._available

    def container(self, name: str) -> ContainerInfo | None:
        return self._container

    def port_holders(self, port: int) -> list[str]:
        return list(self._holders)


class FakeHealth:
    def __init__(self, core: CoreHealth | None = None, cockpit_status: int | None = None) -> None:
        self._core = core
        self._cockpit = cockpit_status
        self.asked: list[str] = []

    def core_health(self, url: str) -> CoreHealth | None:
        self.asked.append(url)
        return self._core

    def http_status(self, url: str) -> int | None:
        self.asked.append(url)
        return self._cockpit


class FakeEnvironment:
    def __init__(self, *, existing: Iterable[Path] = (), tools: Iterable[str] = ()) -> None:
        self._existing = {str(path) for path in existing}
        self._tools = set(tools)

    def path_exists(self, path: Path) -> bool:
        return str(path) in self._existing

    def which(self, name: str) -> str | None:
        return f"C:/tools/{name}" if name in self._tools else None
