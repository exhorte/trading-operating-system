"""Starting the application (ADR 0038, § 4): the links in dependency order, each waited for until it is **really** healthy.

Rules this module keeps, and its tests hold it to:
* every link is **re-observed just before it is started** — a component that appeared meanwhile is kept, never started over;
* a component already healthy is never touched, never gated by what it depends on; only a *start* waits on the links before it;
* what is started is written to the registry **before** it is waited for, so that a crash or a timeout leaves something ``stop`` can end;
* a link that fails stops what depends on it, and nothing else;
* a migration is never applied without a backup taken first, and never over a drifted schema;
* nothing in a command's output reaches a report or an event unmasked.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from trading_os.launcher.events import EventLog, EventSeverity, EventType
from trading_os.launcher.model import (
    Component,
    ComponentObservation,
    ComponentState,
    LauncherConfig,
    Observation,
    OutcomeStatus,
    OwnedContainer,
    OwnedProcess,
    Reason,
    Stage,
    StartReport,
    Step,
    StepAction,
    StepOutcome,
)
from trading_os.launcher.observe import Observer
from trading_os.launcher.plan import build_plan
from trading_os.launcher.ports import (
    CommandRunner,
    DockerActions,
    DockerPort,
    EnvironmentPort,
    ProcessSpawner,
    ProcessTable,
    Sleeper,
    SpawnError,
)
from trading_os.launcher.registry import ProcessRegistry
from trading_os.shared.logging.redaction import redact
from trading_os.shared.time import Clock

DEPENDS_ON = {Stage.SCHEMA: Stage.DATABASE, Stage.CORE: Stage.SCHEMA, Stage.COCKPIT: Stage.CORE}
MIGRATION_ROW = re.compile(r"^(\d{4}_\S+)\s+(applied|pending|DRIFTED)\s*$")
NOT_DONE = {OutcomeStatus.BLOCKED, OutcomeStatus.FAILED}


class Starter:
    def __init__(
        self,
        config: LauncherConfig,
        *,
        observer: Observer,
        docker: DockerPort,
        actions: DockerActions,
        runner: CommandRunner,
        spawner: ProcessSpawner,
        processes: ProcessTable,
        environment: EnvironmentPort,
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
        self._runner = runner
        self._spawner = spawner
        self._processes = processes
        self._environment = environment
        self._registry = registry
        self._events = events
        self._clock = clock
        self._sleeper = sleeper
        self._correlation_id = correlation_id

    def start(self) -> StartReport:
        outcomes: dict[Stage, StepOutcome] = {}
        for stage in (Stage.DATABASE, Stage.SCHEMA, Stage.CORE, Stage.COCKPIT):
            observation = self._observer.observe()  # fresh before every link
            step = build_plan(observation, self._config).step(stage)
            outcomes[stage] = self._link(stage, step, observation, outcomes)
        return StartReport(outcomes=tuple(outcomes.values()))

    # ------------------------------------------------------------------------------------------------ one link

    def _link(self, stage: Stage, step: Step, observation: Observation, done: dict[Stage, StepOutcome]) -> StepOutcome:
        def outcome(status: OutcomeStatus, detail: str = "") -> StepOutcome:
            return StepOutcome(stage=stage, status=status, detail=redact(detail))

        if step.action is StepAction.KEEP:
            return outcome(OutcomeStatus.KEPT, step.detail)
        if step.action is StepAction.SKIP:
            return outcome(OutcomeStatus.SKIPPED, step.detail)
        if step.action is StepAction.BLOCKED:
            if step.reason is Reason.FOREIGN_PROCESS:
                self._emit(EventType.LAUNCHER_PORT_FOREIGN_PROCESS, stage, step.detail, EventSeverity.WARNING)
            return outcome(OutcomeStatus.BLOCKED, f"{step.reason.value} : {step.detail}")
        before = DEPENDS_ON.get(stage)
        if before is not None and done[before].status in NOT_DONE:
            return outcome(OutcomeStatus.BLOCKED, f"dépend de l'étape « {before.value} » qui n'a pas abouti")
        if stage is Stage.DATABASE:
            return self._database(step, outcome)
        if stage is Stage.SCHEMA:
            return self._schema(outcome)
        if stage is Stage.CORE:
            return self._process(
                Component.CORE,
                [str(self._config.venv_python), "-m", "trading_os", "serve"],
                self._config.core_cwd,
                "core",
                self._config.timeouts.core_s,
                EventType.STARTUP_CORE_READY,
                outcome,
            )
        npm = self._environment.which("npm")
        if npm is None:
            return outcome(OutcomeStatus.BLOCKED, "npm est introuvable")
        return self._process(
            Component.COCKPIT,
            [npm, "run", "dev"],
            self._config.cockpit_cwd,
            "cockpit",
            self._config.timeouts.cockpit_s,
            EventType.STARTUP_COCKPIT_READY,
            outcome,
        )

    # ------------------------------------------------------------------------------------------------ database

    def _database(self, step: Step, outcome: Callable[..., StepOutcome]) -> StepOutcome:
        name = self._config.container_name
        if step.action is StepAction.START:
            exists = self._docker.container(name) is not None
            started = (
                self._actions.start_container(name) if exists else self._actions.create_database(self._config.repo_root)
            )
            if not started:
                return self._failed(Stage.DATABASE, outcome, "docker n'a pas pu démarrer le conteneur de la base")
            self._registry.record_container(
                OwnedContainer(name=name, started_at=self._clock.now(), correlation_id=self._correlation_id)
            )
        limit = self._config.timeouts.database_s
        health = self._wait(limit, lambda: self._database_health() == "healthy")
        if not health:
            return self._failed(
                Stage.DATABASE,
                outcome,
                f"le conteneur n'est pas « healthy » après {limit:g} s (état : {self._database_health()})",
            )
        self._emit(EventType.STARTUP_DATABASE_READY, Stage.DATABASE, f"conteneur {name} healthy")
        return outcome(OutcomeStatus.DONE, f"conteneur {name} healthy")

    def _database_health(self) -> str:
        info = self._docker.container(self._config.container_name)
        if info is None or info.status != "running":
            return "absent"
        return info.health or "sans contrôle de santé"

    # ------------------------------------------------------------------------------------------------ schema

    def _schema(self, outcome: Callable[..., StepOutcome]) -> StepOutcome:
        python = str(self._config.venv_python)
        status = self._runner.run([python, "-m", "trading_os", "db", "status"], timeout=60, cwd=self._config.core_cwd)
        rows = [match.groups() for line in status.stdout.splitlines() if (match := MIGRATION_ROW.match(line.strip()))]
        drifted = [name for name, state in rows if state == "DRIFTED"]
        if drifted:
            return self._failed(
                Stage.SCHEMA,
                outcome,
                f"le schéma a dérivé ({', '.join(drifted)}) : aucune migration n'est appliquée par-dessus",
            )
        if status.returncode != 0 and not rows:
            return self._failed(Stage.SCHEMA, outcome, f"« db status » a échoué : {status.stderr.strip()[:200]}")
        pending = [name for name, state in rows if state == "pending"]
        if not pending:
            return outcome(OutcomeStatus.SKIPPED, "le schéma est à jour")
        destination = self._config.backups_dir / f"tradingos-{self._clock.now():%Y%m%d-%H%M%S}.dump"
        if not self._actions.dump_database(self._config.container_name, destination):
            return self._failed(
                Stage.SCHEMA, outcome, "la sauvegarde a échoué : aucune migration n'est appliquée sans elle"
            )
        self._emit(EventType.STARTUP_BACKUP_DONE, Stage.SCHEMA, f"sauvegarde {destination.name}")
        migrated = self._runner.run(
            [python, "-m", "trading_os", "db", "migrate"],
            timeout=self._config.timeouts.migrate_s,
            cwd=self._config.core_cwd,
        )
        if migrated.returncode != 0:
            return self._failed(Stage.SCHEMA, outcome, f"« db migrate » a échoué : {migrated.stderr.strip()[:200]}")
        detail = f"{len(pending)} migration(s) appliquée(s) après la sauvegarde {destination.name}"
        self._emit(EventType.STARTUP_SCHEMA_APPLIED, Stage.SCHEMA, detail)
        return outcome(OutcomeStatus.DONE, detail)

    # ------------------------------------------------------------------------------------------------ core and cockpit

    def _process(
        self,
        component: Component,
        args: list[str],
        cwd: Path,
        prefix: str,
        timeout: float,
        ready_event: EventType,
        outcome: Callable[..., StepOutcome],
    ) -> StepOutcome:
        stage = Stage(component.value)
        log_path = self._config.logs_dir / f"{prefix}-{self._clock.now():%Y%m%d-%H%M%S}.log"
        try:
            pid = self._spawner.spawn(args, cwd=cwd, log_path=log_path)
        except SpawnError as error:
            return self._failed(stage, outcome, f"le processus n'a pas pu être lancé : {error}")
        live = self._wait_visible(pid)
        if live is None or live[0] is None:
            return self._failed(
                stage,
                outcome,
                f"le processus (pid {pid}) n'est pas apparu avec une identité vérifiable ; journal : {log_path}",
            )
        created_at, command_line = live
        self._registry.record(
            OwnedProcess(
                component=component,
                pid=pid,
                created_at=created_at,
                command_line=command_line,
                started_at=self._clock.now(),
                working_directory=str(cwd),
                log_path=str(log_path),
                correlation_id=self._correlation_id,
            )
        )
        self._emit(EventType.LAUNCHER_PROCESS_STARTED, stage, f"pid {pid}, journal {log_path.name}")

        def ready() -> bool:
            return self._observer.observe().component(component).state is ComponentState.HEALTHY

        died = False

        def healthy_or_dead() -> bool:
            nonlocal died
            if ready():
                return True
            if not self._alive(pid):
                died = True
                return True
            return False

        self._wait(timeout, healthy_or_dead)
        if died:
            self._registry.forget(component)
            return self._failed(stage, outcome, f"le processus s'est arrêté avant d'être prêt ; journal : {log_path}")
        item = self._observer.observe().component(component)
        if item.state is not ComponentState.HEALTHY:
            return self._failed(
                stage,
                outcome,
                f"pas prêt après {timeout:g} s ({self._describe(item)}) ; le processus (pid {pid}) tourne encore, « launcher stop » peut l'arrêter ; journal : {log_path}",
            )
        self._emit(ready_event, stage, f"pid {pid}, prêt")
        return outcome(OutcomeStatus.DONE, f"pid {pid}, journal {log_path.name}")

    # ------------------------------------------------------------------------------------------------ helpers

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

    def _wait_visible(self, pid: int) -> tuple[datetime | None, str] | None:
        found: list[tuple[datetime | None, str]] = []

        def seen() -> bool:
            for process in self._processes.processes():
                if process.pid == pid:
                    found.append((process.created_at, process.command_line))
                    return True
            return False

        return found[0] if self._wait(self._config.timeouts.process_visible_s, seen) else None

    def _alive(self, pid: int) -> bool:
        return any(process.pid == pid for process in self._processes.processes())

    @staticmethod
    def _describe(item: ComponentObservation) -> str:
        return f"{item.state.value}{' : ' + item.detail if item.detail else ''}"

    def _failed(self, stage: Stage, outcome: Callable[..., StepOutcome], detail: str) -> StepOutcome:
        self._emit(EventType.STARTUP_FAILED, stage, detail, EventSeverity.ERROR)
        return outcome(OutcomeStatus.FAILED, detail)

    def _emit(
        self, kind: EventType, stage: Stage, diagnostic: str, severity: EventSeverity = EventSeverity.INFO
    ) -> None:
        self._events.emit(
            kind,
            component=stage.value,
            correlation_id=self._correlation_id,
            severity=severity,
            diagnostic=diagnostic,
        )
