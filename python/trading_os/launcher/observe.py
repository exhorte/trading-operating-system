"""What the launcher sees (ADR 0038, § 3): which components are there, who holds their ports, and whether those processes are ours.

A listener is **owned** when it descends from a process the launcher recorded (pid *and* creation time verified), **recognized** when its
command line carries this repository's signature, and **foreign** otherwise. A foreign process is reported and never touched; it is never
taken for a component, whatever it answers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from trading_os.launcher.model import (
    Component,
    ComponentObservation,
    ComponentState,
    CoreHealth,
    EnvironmentFacts,
    LauncherConfig,
    Listener,
    Observation,
    OwnedProcess,
    Ownership,
    ProcessInfo,
)
from trading_os.launcher.ports import DockerPort, EnvironmentPort, HealthProbe, ProcessTable
from trading_os.launcher.registry import ProcessRegistry, verify_owned
from trading_os.shared.time import Clock

MAX_ANCESTORS = 64
ALL_INTERFACES = frozenset({"0.0.0.0", "::"})


def _normalise(text: str) -> str:
    return text.lower().replace("/", "\\")


def markers_of(component: Component, config: LauncherConfig) -> tuple[str, ...]:
    """The fragments a command line must carry to be recognized as this repository's. The repository path is always one of them, so another
    checkout — or another project's Next.js server — is foreign."""
    repo = _normalise(str(config.repo_root))
    if component is Component.CORE:
        return (repo, "trading_os", "serve")
    if component is Component.COCKPIT:
        return (repo, "next")
    return (repo,)


def _ancestry(pid: int, by_pid: Mapping[int, ProcessInfo]) -> set[int]:
    chain: set[int] = set()
    current: int | None = pid
    while current is not None and current not in chain and len(chain) < MAX_ANCESTORS:
        chain.add(current)
        process = by_pid.get(current)
        current = process.parent_pid if process is not None else None
    return chain


def classify_owner(
    pid: int,
    component: Component,
    by_pid: Mapping[int, ProcessInfo],
    owned: Sequence[OwnedProcess],
    config: LauncherConfig,
) -> Ownership:
    chain = _ancestry(pid, by_pid)
    if any(entry.component is component and entry.pid in chain for entry in owned):
        return Ownership.OWNED
    process = by_pid.get(pid)
    if process is not None:
        command_line = _normalise(process.command_line)
        if all(marker in command_line for marker in markers_of(component, config)):
            return Ownership.RECOGNIZED
    return Ownership.FOREIGN


class Observer:
    def __init__(
        self,
        config: LauncherConfig,
        *,
        processes: ProcessTable,
        docker: DockerPort,
        health: HealthProbe,
        environment: EnvironmentPort,
        registry: ProcessRegistry,
        clock: Clock,
    ) -> None:
        self._config = config
        self._processes = processes
        self._docker = docker
        self._health = health
        self._environment = environment
        self._registry = registry
        self._clock = clock

    def observe(self) -> Observation:
        config = self._config
        table = self._processes.processes()
        by_pid = {process.pid: process for process in table}
        listeners = self._processes.listeners(config.watched_ports)
        snapshot = self._registry.load()
        owned = verify_owned(snapshot.owned, table)
        docker_ok = self._docker.available()
        environment = EnvironmentFacts(
            docker_available=docker_ok,
            venv_python_present=self._environment.path_exists(config.venv_python),
            env_file_present=self._environment.path_exists(config.env_file),
            npm_available=self._environment.which("npm") is not None,
        )
        core, core_health = self._core(listeners, by_pid, owned)
        return Observation(
            observed_at=self._clock.now(),
            environment=environment,
            components=(
                self._database(docker_ok, listeners, by_pid),
                core,
                self._cockpit(listeners, by_pid, owned),
            ),
            owned=owned,
            registry_problem=snapshot.problem,
            core_health=core_health,
        )

    # ------------------------------------------------------------------------------------------------ database

    def _database(
        self, docker_ok: bool, listeners: Sequence[Listener], by_pid: Mapping[int, ProcessInfo]
    ) -> ComponentObservation:
        config = self._config
        component = Component.DATABASE
        if not docker_ok:
            return ComponentObservation(
                component=component,
                state=ComponentState.UNAVAILABLE,
                detail="Docker Desktop ne répond pas ; le lanceur ne le démarre pas",
            )
        others = [name for name in self._docker.port_holders(config.db_port) if name != config.container_name]
        if others:
            return ComponentObservation(
                component=component,
                state=ComponentState.FOREIGN,
                ownership=Ownership.FOREIGN,
                detail=f"le port {config.db_port} est publié par le conteneur {', '.join(others)}",
            )
        info = self._docker.container(config.container_name)
        if info is None or info.status in {"exited", "created"}:
            holders = [item for item in listeners if item.port == config.db_port]
            if holders:
                holder = holders[0]
                name = by_pid[holder.pid].name if holder.pid in by_pid else "un processus"
                return ComponentObservation(
                    component=component,
                    state=ComponentState.FOREIGN,
                    ownership=Ownership.FOREIGN,
                    pid=holder.pid,
                    detail=f"le port {config.db_port} est tenu par {name} (pid {holder.pid}), pas par {config.container_name}",
                )
            return ComponentObservation(component=component, state=ComponentState.ABSENT)

        def seen(state: ComponentState, detail: str) -> ComponentObservation:
            return ComponentObservation(component=component, state=state, ownership=Ownership.RECOGNIZED, detail=detail)

        if info.status != "running":
            return seen(ComponentState.UNHEALTHY, f"le conteneur est « {info.status} »")
        if config.db_port not in info.host_ports:
            published = ", ".join(str(port) for port in info.host_ports) or "aucun port"
            return seen(
                ComponentState.UNHEALTHY, f"le conteneur publie {published}, le port attendu est {config.db_port}"
            )
        if info.health == "healthy":
            return seen(ComponentState.HEALTHY, f"conteneur {config.container_name} (healthy), port {config.db_port}")
        if info.health == "starting":
            return seen(ComponentState.STARTING, "le conteneur démarre, sa santé n'est pas encore « healthy »")
        if info.health is None:
            return seen(ComponentState.UNHEALTHY, "le conteneur n'a pas de contrôle de santé")
        return seen(ComponentState.UNHEALTHY, f"la santé du conteneur est « {info.health} »")

    # ------------------------------------------------------------------------------------------------ core

    def _core(
        self, listeners: Sequence[Listener], by_pid: Mapping[int, ProcessInfo], owned: Sequence[OwnedProcess]
    ) -> tuple[ComponentObservation, CoreHealth | None]:
        """The core as seen, and what it answered (kept for the diagnosis; ``None`` when nothing was asked or nothing answered)."""
        config = self._config
        component = Component.CORE
        api = [item for item in listeners if item.port == config.api_port]
        link = [item for item in listeners if item.port == config.ea_link_port]
        if not api and not link:
            return ComponentObservation(component=component, state=ComponentState.ABSENT), None
        verdicts = [(item, classify_owner(item.pid, component, by_pid, owned, config)) for item in api + link]
        for item, ownership in verdicts:
            if ownership is Ownership.FOREIGN:
                return self._foreign(component, item, by_pid), None
        ownership = Ownership.OWNED if any(o is Ownership.OWNED for _, o in verdicts) else Ownership.RECOGNIZED
        pid = (api or link)[0].pid

        def seen(
            state: ComponentState, detail: str, health: CoreHealth | None = None
        ) -> tuple[ComponentObservation, CoreHealth | None]:
            observed = ComponentObservation(
                component=component, state=state, ownership=ownership, pid=pid, detail=detail
            )
            return observed, health

        if not api:
            return seen(ComponentState.UNHEALTHY, f"le port {config.api_port} de l'API n'écoute pas")
        health = self._health.core_health(f"http://{config.api_host}:{config.api_port}/api/system/health")
        if health is None:
            return seen(ComponentState.UNHEALTHY, "le cœur n'a pas répondu à /api/system/health")
        if not health.database_up:
            return seen(ComponentState.UNHEALTHY, "le cœur dit que sa base est injoignable", health)
        if health.status == "critical":
            return seen(ComponentState.UNHEALTHY, "le cœur se déclare en état critique", health)
        if not link:
            return seen(ComponentState.UNHEALTHY, f"le lien agent ({config.ea_link_port}) n'écoute pas", health)
        return seen(
            ComponentState.HEALTHY,
            f"version {health.version}, statut {health.status}, {health.findings} signalement(s), ports {config.api_port} et {config.ea_link_port}",
            health,
        )

    # ------------------------------------------------------------------------------------------------ cockpit

    def _cockpit(
        self, listeners: Sequence[Listener], by_pid: Mapping[int, ProcessInfo], owned: Sequence[OwnedProcess]
    ) -> ComponentObservation:
        config = self._config
        component = Component.COCKPIT
        found = [item for item in listeners if item.port == config.cockpit_port]
        if not found:
            return ComponentObservation(component=component, state=ComponentState.ABSENT)
        verdicts = [(item, classify_owner(item.pid, component, by_pid, owned, config)) for item in found]
        for item, ownership in verdicts:
            if ownership is Ownership.FOREIGN:
                return self._foreign(component, item, by_pid)
        ownership = Ownership.OWNED if any(o is Ownership.OWNED for _, o in verdicts) else Ownership.RECOGNIZED
        warnings = tuple(
            f"écoute sur toutes les interfaces ({item.address}) : à lier à {config.cockpit_host}"
            for item in found
            if item.address in ALL_INTERFACES
        )
        status = self._health.http_status(f"http://{config.cockpit_host}:{config.cockpit_port}/")
        healthy = status is not None and 200 <= status < 400
        return ComponentObservation(
            component=component,
            state=ComponentState.HEALTHY if healthy else ComponentState.UNHEALTHY,
            ownership=ownership,
            pid=found[0].pid,
            detail=f"HTTP {status}" if status is not None else "aucune réponse HTTP",
            warnings=warnings,
        )

    # ------------------------------------------------------------------------------------------------ shared

    @staticmethod
    def _foreign(component: Component, holder: Listener, by_pid: Mapping[int, ProcessInfo]) -> ComponentObservation:
        process = by_pid.get(holder.pid)
        name = process.name if process is not None else "un processus"
        return ComponentObservation(
            component=component,
            state=ComponentState.FOREIGN,
            ownership=Ownership.FOREIGN,
            pid=holder.pid,
            detail=f"le port {holder.port} est tenu par {name} (pid {holder.pid}), qui n'est pas de ce dépôt",
        )
