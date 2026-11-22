"""The launcher's vocabulary (ADR 0038): what is observed, what is planned, what is owned. Pure data — no I/O, no secret."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from trading_os.domain.primitives import DomainModel


class Component(StrEnum):
    DATABASE = "database"
    CORE = "core"
    COCKPIT = "cockpit"


class Stage(StrEnum):
    """A step of the start-up, in dependency order. The schema is a stage but not a component: nothing runs for it."""

    DATABASE = "database"
    SCHEMA = "schema"
    CORE = "core"
    COCKPIT = "cockpit"


class ComponentState(StrEnum):
    ABSENT = "ABSENT"  # nothing there: it can be started
    STARTING = "STARTING"  # it is there and has not finished starting
    HEALTHY = "HEALTHY"  # it is there and answers
    UNHEALTHY = "UNHEALTHY"  # it is there and does not answer properly — never started over
    FOREIGN = "FOREIGN"  # its port is held by something that is not ours — never touched
    UNAVAILABLE = "UNAVAILABLE"  # it cannot even be looked at (Docker does not answer)


class Ownership(StrEnum):
    NONE = "NONE"  # nobody there
    OWNED = "OWNED"  # descends from a process the launcher started (pid and creation time verified)
    RECOGNIZED = "RECOGNIZED"  # carries this repository's signature, but the launcher did not start it
    FOREIGN = "FOREIGN"  # anything else


class ProcessInfo(DomainModel):
    pid: int
    parent_pid: int = 0
    name: str
    executable: str | None = None
    command_line: str = ""
    created_at: datetime | None = None  # None = unknown, and an unknown identity is never trusted


class Listener(DomainModel):
    address: str
    port: int
    pid: int


class ContainerInfo(DomainModel):
    name: str
    status: str  # Docker's State.Status: running, exited, created, paused…
    health: str | None = None  # Docker's State.Health.Status, None when the container has no health check
    host_ports: tuple[int, ...] = ()


class Mt5WorkersFacts(DomainModel):
    """``mt5Workers`` of the core's health (ADR 0037): MT5 worker processes started, ended, and alive. The core owns them, the launcher only reads."""

    spawned: int
    ended: int
    alive: int


class CoreHealth(DomainModel):
    """The few facts of ``GET /api/system/health`` the launcher needs — it answers « is it up », the readiness report answers the rest.

    The three optional fields feed the diagnosis (ADR 0039, § 6). ``None`` means *the core did not say* (an older core, or a value of the wrong
    kind): never zero, because « no agent connected » and « unknown » are not the same finding."""

    status: str
    version: str
    database_up: bool
    findings: int = 0
    started_at: datetime | None = None
    agents_connected: int | None = None
    mt5_workers: Mt5WorkersFacts | None = None
    execution_mode: str | None = None


class EnvironmentFacts(DomainModel):
    docker_available: bool
    venv_python_present: bool
    env_file_present: bool  # existence only: the launcher's tests prove it cannot read the file
    npm_available: bool


class OwnedProcess(DomainModel):
    """A process the launcher started. The creation time is the proof against the reuse of a pid."""

    component: Component
    pid: int
    created_at: datetime
    command_line: str
    started_at: datetime
    working_directory: str | None = None
    log_path: str | None = None
    correlation_id: str


class OwnedContainer(DomainModel):
    """A container the launcher started. It is stopped on ``launcher stop`` only for that reason (or with ``--include-database``)."""

    name: str
    started_at: datetime
    correlation_id: str


class ComponentObservation(DomainModel):
    component: Component
    state: ComponentState
    ownership: Ownership = Ownership.NONE
    pid: int | None = None
    detail: str = ""
    warnings: tuple[str, ...] = ()


class Observation(DomainModel):
    observed_at: datetime
    environment: EnvironmentFacts
    components: tuple[ComponentObservation, ...]
    owned: tuple[OwnedProcess, ...] = ()
    registry_problem: str | None = None
    core_health: CoreHealth | None = None  # what the core answered, kept for the diagnosis; None = no answer

    def component(self, component: Component) -> ComponentObservation:
        for item in self.components:
            if item.component is component:
                return item
        raise KeyError(component)


class StepAction(StrEnum):
    KEEP = "KEEP"  # healthy: leave it alone
    START = "START"
    WAIT = "WAIT"  # starting: wait, do not start again
    MIGRATE = "MIGRATE"
    SKIP = "SKIP"  # nothing to do for this stage
    BLOCKED = "BLOCKED"  # cannot proceed, and says why


class Reason(StrEnum):
    ALREADY_HEALTHY = "ALREADY_HEALTHY"
    NOT_RUNNING = "NOT_RUNNING"
    STILL_STARTING = "STILL_STARTING"
    UNHEALTHY = "UNHEALTHY"
    FOREIGN_PROCESS = "FOREIGN_PROCESS"
    DOCKER_UNAVAILABLE = "DOCKER_UNAVAILABLE"
    VENV_MISSING = "VENV_MISSING"
    ENV_FILE_MISSING = "ENV_FILE_MISSING"
    NPM_MISSING = "NPM_MISSING"
    DEPENDENCY_BLOCKED = "DEPENDENCY_BLOCKED"
    SCHEMA_IN_USE = "SCHEMA_IN_USE"
    SCHEMA_TO_APPLY = "SCHEMA_TO_APPLY"


class Step(DomainModel):
    stage: Stage
    action: StepAction
    reason: Reason
    detail: str = ""
    working_directory: str | None = None  # where a START must run (the core is not importable from the repository root)


class Plan(DomainModel):
    steps: tuple[Step, ...]

    def step(self, stage: Stage) -> Step:
        for item in self.steps:
            if item.stage is stage:
                return item
        raise KeyError(stage)

    @property
    def blocked(self) -> bool:
        return any(item.action is StepAction.BLOCKED for item in self.steps)

    @property
    def starts(self) -> tuple[Step, ...]:
        return tuple(item for item in self.steps if item.action is StepAction.START)

    @property
    def changes_nothing(self) -> bool:
        return all(item.action in {StepAction.KEEP, StepAction.SKIP} for item in self.steps)


class OutcomeStatus(StrEnum):
    DONE = "DONE"  # it was started / applied by this run
    KEPT = "KEPT"  # already healthy: left alone
    SKIPPED = "SKIPPED"  # nothing to do
    BLOCKED = "BLOCKED"  # not attempted, and says why
    FAILED = "FAILED"  # attempted and did not work


class StepOutcome(DomainModel):
    stage: Stage
    status: OutcomeStatus
    detail: str = ""


class StartReport(DomainModel):
    outcomes: tuple[StepOutcome, ...]

    @property
    def ok(self) -> bool:
        return all(item.status not in {OutcomeStatus.BLOCKED, OutcomeStatus.FAILED} for item in self.outcomes)

    def outcome(self, stage: Stage) -> StepOutcome:
        for item in self.outcomes:
            if item.stage is stage:
                return item
        raise KeyError(stage)


class StopStatus(StrEnum):
    STOPPED = "STOPPED"
    WOULD_STOP = "WOULD_STOP"  # dry run
    NOT_RUNNING = "NOT_RUNNING"
    NOT_OURS = "NOT_OURS"  # something runs, the launcher did not start it: reported, never touched
    REFUSED = "REFUSED"  # a safety rule says not now (the database is not stopped under a running core)
    FAILED = "FAILED"


class StopOutcome(DomainModel):
    component: Component
    status: StopStatus
    detail: str = ""


class StopReport(DomainModel):
    outcomes: tuple[StopOutcome, ...]
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return all(item.status is not StopStatus.FAILED for item in self.outcomes)

    def outcome(self, component: Component) -> StopOutcome:
        for item in self.outcomes:
            if item.component is component:
                return item
        raise KeyError(component)


class Timeouts(DomainModel):
    """Values set by Claude, to be read (ADR 0038): how long each link may take to become healthy, and the polling step."""

    database_s: float = 90.0
    core_s: float = 60.0
    cockpit_s: float = 120.0
    process_visible_s: float = 5.0
    migrate_s: float = 180.0
    stop_grace_s: float = 30.0
    stop_confirm_s: float = 10.0
    poll_s: float = 2.0


class LauncherConfig(DomainModel):
    """Where things are and which ports they use. Built from the core's own settings; the launcher invents none of it."""

    repo_root: Path
    container_name: str = "tradingos-timescaledb"
    db_port: int = 5433
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    ea_link_port: int = 9765
    cockpit_host: str = "127.0.0.1"
    cockpit_port: int = 3000
    timeouts: Timeouts = Timeouts()

    @property
    def logs_dir(self) -> Path:
        return self.var_dir / "logs"

    @property
    def backups_dir(self) -> Path:
        return self.repo_root / "exports" / "backups"

    @property
    def lock_path(self) -> Path:
        return self.var_dir / "launcher.lock"

    @property
    def venv_python(self) -> Path:
        return self.repo_root / "python" / ".venv" / "Scripts" / "python.exe"

    @property
    def core_cwd(self) -> Path:
        """``python -m trading_os`` is importable from here (audit D2)."""
        return self.repo_root / "python"

    @property
    def cockpit_cwd(self) -> Path:
        return self.repo_root

    @property
    def env_file(self) -> Path:
        return self.repo_root / ".env"

    @property
    def var_dir(self) -> Path:
        return self.repo_root / "var" / "launcher"

    @property
    def registry_path(self) -> Path:
        return self.var_dir / "state.json"

    @property
    def events_dir(self) -> Path:
        return self.var_dir

    @property
    def terminals_path(self) -> Path:
        """The MetaTrader terminals registry (ADR 0039 § 4)."""
        return self.var_dir / "terminals.json"

    @property
    def locks_dir(self) -> Path:
        """One lock file per terminal (ADR 0039 § 4, rule 4)."""
        return self.var_dir / "locks"

    @property
    def watched_ports(self) -> tuple[int, ...]:
        return (self.db_port, self.api_port, self.ea_link_port, self.cockpit_port)
