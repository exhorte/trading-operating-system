"""The vocabulary of the MetaTrader 5 side (ADR 0038 § 6, ADR 0039 § 4): what is found, what is remembered, what is planned.

Pure data. No model has a field that could carry a secret — a password, a token, an API key — and none keeps the command line a terminal was
started with (it can hold ``/login:`` and ``/password:``). *Observed* facts about an account (server, login, type) are not kept here at all: they
are read live from the core and the EA.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from trading_os.domain.primitives import DomainModel

# ------------------------------------------------------------------------------------------------ what is found


class DiscoverySource(StrEnum):
    REGISTRY = "REGISTRY"  # the list of installed programs
    KNOWN_DIRECTORY = "KNOWN_DIRECTORY"  # a folder of Program Files whose name says MetaTrader
    RUNNING_PROCESS = "RUNNING_PROCESS"  # a terminal64.exe that is running
    REGISTERED = "REGISTERED"  # a path Exhorte registered


class EaInstallKind(StrEnum):
    JUNCTION = "JUNCTION"  # MQL5\Experts\<name> is a junction (today: to the repository, ADR 0038 A4)
    DIRECTORY = "DIRECTORY"  # a real folder (a deployed copy)


class EaInstall(DomainModel):
    kind: EaInstallKind
    name: str
    target: str | None = None


class RunningTerminal(DomainModel):
    pid: int
    created_at: datetime | None = None
    portable: bool = False
    config_file_given: bool = (
        False  # started with /config: — only the fact, never the path nor anything else of the command line
    )


class DataFolder(DomainModel):
    terminal_id: str
    path: str
    portable: bool = False
    origin: str | None = None
    experts_present: bool = False
    presets_present: bool = False
    files_present: bool = False
    link_file_present: bool = (
        False  # the file the agent reads to authenticate with the core exists — its content is never read
    )
    eas: tuple[EaInstall, ...] = ()  # our agent, as installed
    third_party_experts: tuple[
        str, ...
    ] = ()  # compiled EAs found loose in MQL5\Experts that are not ours: installed, not necessarily attached


class Installation(DomainModel):
    install_path: str
    exe_path: str
    version: str | None = None
    sources: tuple[DiscoverySource, ...] = ()
    running: tuple[RunningTerminal, ...] = ()
    data_folders: tuple[DataFolder, ...] = ()


class RejectedCandidate(DomainModel):
    path: str
    source: DiscoverySource
    reason: str


class DiscoveryResult(DomainModel):
    observed_at: datetime
    installations: tuple[Installation, ...] = ()
    rejected: tuple[RejectedCandidate, ...] = ()
    unmatched_data_folders: tuple[str, ...] = ()


class Mt5Config(DomainModel):
    """Where to look. Built from the environment by the wiring; the discovery invents none of it."""

    program_roots: tuple[str, ...] = ()
    data_root: str | None = None


# ------------------------------------------------------------------------------------------------ what is remembered

FIELD_LABELS = {
    "account_id": "compte Trading OS",
    "expected_login": "login attendu",
    "chart": "graphique (symbole et période)",
    "magic": "numéro magique",
    "allowed_symbols": "symboles autorisés",
    "provider": "fournisseur",
    "product": "produit",
}


class TerminalSource(StrEnum):
    DISCOVERED = "DISCOVERED"
    MANUAL = "MANUAL"


class ChartSpec(DomainModel):
    symbol: str
    period: str


class DeclaredTerminal(DomainModel):
    """What Exhorte declares about a terminal. Compared with what the terminal and the EA report, never trusted instead of it (ADR 0036)."""

    account_id: str | None = None
    expected_login: str | None = None
    chart: ChartSpec | None = None
    magic: int | None = None
    allowed_symbols: tuple[str, ...] = ()
    provider: str | None = None
    product: str | None = None

    def missing_fields(self) -> tuple[str, ...]:
        missing = []
        for name in FIELD_LABELS:
            value = getattr(self, name)
            if value is None or value == ():
                missing.append(name)
        return tuple(missing)


class OperationKind(StrEnum):
    IDLE = "IDLE"
    DEPLOYING = "DEPLOYING"
    TERMINAL_STOPPING = "TERMINAL_STOPPING"
    TERMINAL_STARTING = "TERMINAL_STARTING"
    EA_LOADING = "EA_LOADING"


class OperationState(DomainModel):
    """What the launcher is doing to a terminal right now. Persisted, with a deadline: an operation left behind past it is never resumed silently."""

    kind: OperationKind = OperationKind.IDLE
    deployment_id: str | None = None
    step: str | None = None
    started_at: datetime | None = None
    deadline: datetime | None = None


def is_overdue(operation: OperationState, now: datetime) -> bool:
    """An operation past its deadline. An idle terminal has no operation to be late."""
    return operation.kind is not OperationKind.IDLE and operation.deadline is not None and now > operation.deadline


class DeploymentRecord(DomainModel):
    """What the launcher last put in a terminal (ADR 0039 § 4). A memory of an act, never a proof of the present: the file is read again."""

    deployment_id: str
    agent_version: str
    ex5_sha256: str
    deployed_at: datetime
    target_file: str
    expert_path: str  # relative to MQL5\Experts, without the extension — what the preset and the start-up file name
    build_name: str
    previous_sha256: str | None = None


class PreparedRecord(DomainModel):
    """What the launcher last prepared for a terminal: the preset in its Presets folder and the start-up file it keeps itself."""

    prepared_at: datetime
    preset_path: str
    preset_sha256: str
    startup_path: str
    startup_sha256: str


class StateRecord(DomainModel):
    """The last state of the deployment the launcher saw — kept to check the table of transitions and to recognise a disconnection, never read as proof."""

    state: str
    at: datetime
    codes: tuple[str, ...] = ()


class TerminalSnapshot(DomainModel):
    """What a read-only look at a running terminal said: the login it is on and how many positions and pending orders it holds. ``None`` = it did not say."""

    login: str | None = None
    positions: int | None = None
    orders: int | None = None


class VerdictCondition(DomainModel):
    code: str
    label: str
    light: str  # GREEN / RED / PENDING
    detail: str


class TerminalVerdict(DomainModel):
    """The core's reading of the conditions for one terminal (ADR 0039 § 5): served by the core, never recomputed by the launcher."""

    verdict: str | None = None  # READY / VALIDATING / BLOCKED
    red_codes: tuple[str, ...] = ()
    pending_codes: tuple[str, ...] = ()
    warning_codes: tuple[str, ...] = ()
    header_code: str | None = None
    heartbeat_age_s: float | None = None
    agent_version: str | None = None
    execution_authorization: str | None = None
    conditions: tuple[VerdictCondition, ...] = ()


class CenterFacts(DomainModel):
    """What the core says of a terminal's agent. ``reachable`` False = the core could not be asked, which is neither a hello nor its absence."""

    reachable: bool
    hello_received: bool | None = None
    verdict: TerminalVerdict | None = None


class TerminalEntry(DomainModel):
    terminal_id: str
    label: str
    install_path: str
    data_path: str
    portable: bool
    source: TerminalSource
    declared: DeclaredTerminal = DeclaredTerminal()
    operation: OperationState = OperationState()
    deployment: DeploymentRecord | None = None
    prepared: PreparedRecord | None = None
    last_state: StateRecord | None = None
    registered_at: datetime
    updated_at: datetime


class TerminalsSnapshot(DomainModel):
    terminals: tuple[TerminalEntry, ...] = ()
    problem: str | None = None

    def find(self, terminal_id: str) -> TerminalEntry | None:
        for entry in self.terminals:
            if entry.terminal_id == terminal_id:
                return entry
        return None


# ------------------------------------------------------------------------------------------------ what is planned


class PlanStatus(StrEnum):
    UNREGISTERED = "UNREGISTERED"
    INCOMPLETE = "INCOMPLETE"
    DECLARED = "DECLARED"
    NOT_FOUND = "NOT_FOUND"


class TerminalPlan(DomainModel):
    terminal_id: str
    label: str | None = None
    install_path: str
    data_path: str
    portable: bool = False
    version: str | None = None
    registered: bool = False
    running_pid: int | None = None
    ea_summary: str = ""
    presets_present: bool | None = None
    status: PlanStatus
    missing: tuple[str, ...] = ()
    next_step: str = ""


class Mt5Plan(DomainModel):
    observed_at: datetime
    terminals: tuple[TerminalPlan, ...] = ()
    registry_problem: str | None = None
    installations_found: int = 0


class Mt5Facts(DomainModel):
    """What the diagnosis is given about MetaTrader: the discovery (``None`` when it failed, with ``error``) and the registry."""

    discovery: DiscoveryResult | None = None
    snapshot: TerminalsSnapshot = TerminalsSnapshot()
    error: str | None = None
