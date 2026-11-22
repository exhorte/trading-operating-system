"""Stopping (ADR 0038, § 5): **only what the registry says the launcher started**, proven by pid and creation time — never a process because it
is on a port or carries a name. Order: cockpit, core (asked politely first, ended only after a grace period), then the database if the launcher
started it. MetaTrader and its agent are not touched, no position is closed, no order is sent: stopping Trading OS is not trading.
"""

from __future__ import annotations

from collections.abc import Callable

from trading_os.launcher.events import EventLog, EventSeverity, EventType
from trading_os.launcher.model import (
    Component,
    ComponentState,
    LauncherConfig,
    Observation,
    OwnedProcess,
    StopOutcome,
    StopReport,
    StopStatus,
)
from trading_os.launcher.observe import Observer, markers_of
from trading_os.launcher.ports import DockerActions, DockerPort, ProcessController, ProcessTable, Sleeper
from trading_os.launcher.registry import ProcessRegistry
from trading_os.shared.logging.redaction import redact
from trading_os.shared.time import Clock

LABELS = {Component.COCKPIT: "cockpit", Component.CORE: "cœur", Component.DATABASE: "base"}


class Stopper:
    def __init__(
        self,
        config: LauncherConfig,
        *,
        observer: Observer,
        docker: DockerPort,
        actions: DockerActions,
        controller: ProcessController,
        processes: ProcessTable,
        registry: ProcessRegistry,
        events: EventLog,
        clock: Clock,
        sleeper: Sleeper,
        correlation_id: str,
    ) -> None:
        self._config = config
        self._observer = observer
        self._docker = docker
        self._actions = actions
        self._controller = controller
        self._processes = processes
        self._registry = registry
        self._events = events
        self._clock = clock
        self._sleeper = sleeper
        self._correlation_id = correlation_id

    def stop(self, *, include_database: bool = False, dry_run: bool = False) -> StopReport:
        observation = self._observer.observe()
        owned = {entry.component: entry for entry in observation.owned}
        if not dry_run:
            self._forget_stale(owned)
        outcomes = [
            self._process(Component.COCKPIT, owned, observation, dry_run, graceful=False),
            self._process(Component.CORE, owned, observation, dry_run, graceful=True),
            self._database(include_database, dry_run),
        ]
        warnings = () if dry_run else self._orphan_workers()
        return StopReport(outcomes=tuple(outcomes), warnings=warnings)

    # ------------------------------------------------------------------------------------------------ cockpit and core

    def _process(
        self,
        component: Component,
        owned: dict[Component, OwnedProcess],
        observation: Observation,
        dry_run: bool,
        *,
        graceful: bool,
    ) -> StopOutcome:
        def outcome(status: StopStatus, detail: str = "") -> StopOutcome:
            return StopOutcome(component=component, status=status, detail=redact(detail))

        entry = owned.get(component)
        if entry is None:
            item = observation.component(component)
            if item.state is ComponentState.ABSENT:
                return outcome(StopStatus.NOT_RUNNING, "rien ne tourne")
            if item.state is ComponentState.FOREIGN:
                return outcome(
                    StopStatus.NOT_OURS,
                    f"un processus étranger tient le port (pid {item.pid}) : il n'est jamais touché",
                )
            return outcome(
                StopStatus.NOT_OURS,
                f"tourne (pid {item.pid}) mais le lanceur ne l'a pas démarré : ferme sa fenêtre, "
                f"ou « launcher adopt {component.value} » puis « launcher stop »",
            )
        if dry_run:
            return outcome(
                StopStatus.WOULD_STOP,
                f"pid {entry.pid} (démarré par le lanceur le {entry.started_at:%Y-%m-%d %H:%M} UTC)",
            )
        timeouts = self._config.timeouts
        if (
            graceful
            and self._controller.request_stop(entry.pid)
            and self._wait(timeouts.stop_grace_s, lambda: not self._alive(entry.pid))
        ):
            return self._stopped(component, entry, outcome, "arrêt demandé, le processus s'est terminé de lui-même")
        if self._alive(entry.pid):
            self._controller.terminate_tree(entry.pid)
            if not self._wait(timeouts.stop_confirm_s, lambda: not self._alive(entry.pid)):
                self._events.emit(
                    EventType.LAUNCHER_STOP_REFUSED,
                    component=component.value,
                    correlation_id=self._correlation_id,
                    severity=EventSeverity.ERROR,
                    diagnostic=f"pid {entry.pid} toujours vivant après l'arrêt forcé",
                )
                return outcome(
                    StopStatus.FAILED, f"le processus (pid {entry.pid}) est toujours vivant après l'arrêt forcé"
                )
            return self._stopped(component, entry, outcome, "arrêt forcé de l'arbre du processus")
        return self._stopped(component, entry, outcome, "le processus s'était déjà terminé")

    def _stopped(
        self, component: Component, entry: OwnedProcess, outcome: Callable[..., StopOutcome], how: str
    ) -> StopOutcome:
        self._registry.forget(component)
        self._events.emit(
            EventType.LAUNCHER_PROCESS_STOPPED,
            component=component.value,
            correlation_id=self._correlation_id,
            diagnostic=f"pid {entry.pid} : {how}",
        )
        return outcome(StopStatus.STOPPED, f"pid {entry.pid} : {how}")

    # ------------------------------------------------------------------------------------------------ database

    def _database(self, include_database: bool, dry_run: bool) -> StopOutcome:
        name = self._config.container_name

        def outcome(status: StopStatus, detail: str = "") -> StopOutcome:
            return StopOutcome(component=Component.DATABASE, status=status, detail=detail)

        info = self._docker.container(name)
        recorded = any(item.name == name for item in self._registry.load().containers)
        if info is None or info.status != "running":
            if recorded and not dry_run:
                self._registry.forget_container(name)
            return outcome(StopStatus.NOT_RUNNING, "le conteneur ne tourne pas")
        if not (recorded or include_database):
            return outcome(
                StopStatus.NOT_OURS,
                f"le conteneur {name} tourne mais le lanceur ne l'a pas démarré : « launcher stop --include-database » pour l'arrêter",
            )
        if not dry_run and self._observer.observe().component(Component.CORE).state is not ComponentState.ABSENT:
            return outcome(StopStatus.REFUSED, "un cœur tourne encore : la base n'est pas arrêtée sous lui")
        if dry_run:
            return outcome(StopStatus.WOULD_STOP, f"docker stop {name}")
        if not self._actions.stop_container(name):
            return outcome(StopStatus.FAILED, f"« docker stop {name} » a échoué")
        self._registry.forget_container(name)
        self._events.emit(
            EventType.LAUNCHER_PROCESS_STOPPED,
            component=Component.DATABASE.value,
            correlation_id=self._correlation_id,
            diagnostic=f"conteneur {name} arrêté",
        )
        return outcome(StopStatus.STOPPED, f"conteneur {name} arrêté (les données sont dans le volume)")

    # ------------------------------------------------------------------------------------------------ after

    def _forget_stale(self, verified: dict[Component, OwnedProcess]) -> None:
        for entry in self._registry.load().owned:
            if verified.get(entry.component) != entry:
                self._registry.forget(entry.component)  # gone, or its pid was recycled: it is no longer ours

    def _orphan_workers(self) -> tuple[str, ...]:
        if self._observer.observe().component(Component.CORE).state is not ComponentState.ABSENT:
            return ()
        markers = (*markers_of(Component.DATABASE, self._config), "mt5.worker")
        orphans = [
            process
            for process in self._processes.processes()
            if all(marker in process.command_line.lower().replace("/", "\\") for marker in markers)
        ]
        return tuple(
            f"un worker MT5 (pid {process.pid}) tourne encore sans cœur : non touché (il n'appartient pas au lanceur)"
            for process in orphans
        )

    # ------------------------------------------------------------------------------------------------ helpers

    def _alive(self, pid: int) -> bool:
        return any(process.pid == pid for process in self._processes.processes())

    def _wait(self, limit: float, condition: Callable[[], bool]) -> bool:
        waited = 0.0
        step = self._config.timeouts.poll_s
        while True:
            if condition():
                return True
            if waited >= limit:
                return False
            self._sleeper.sleep(step)
            waited += step
