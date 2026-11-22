"""The read model of the System Center (ADR 0039 § 8, I8): what the cockpit shows of the MetaTrader terminals and their agents.

Pure data. Every value is something a service *read* — the launcher's registry (what Exhorte declared, what was deployed, the last state journalled), the agent's
own ``hello`` and heartbeat, the core's identification and readiness — never a status invented for the screen. A field the source did not give is ``None``.
Nothing here carries a secret: no token, no password, no command line; paths are the registry's own, shown to the person who owns the machine.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from trading_os.domain.primitives import DomainModel


class DeclaredView(DomainModel):
    account_id: str | None = None
    expected_login: str | None = None
    chart_symbol: str | None = None
    chart_period: str | None = None
    magic: int | None = None
    allowed_symbols: list[str] = Field(default_factory=list)
    provider: str | None = None
    product: str | None = None


class DeploymentView(DomainModel):
    agent_version: str
    deployed_at: datetime | None = None
    ex5_sha256: str | None = None
    expert_path: str | None = None


class RegisteredTerminal(DomainModel):
    terminal_id: str
    label: str
    install_path: str
    data_path: str
    portable: bool = False
    declared: DeclaredView = DeclaredView()
    deployment: DeploymentView | None = None
    operation: str | None = None  # the launcher's operation in progress, if any
    last_state: str | None = None  # the last state of the deployment the launcher journalled — a memory, never a proof
    last_state_at: datetime | None = None


class ProtectionsView(DomainModel):
    max_volume_per_order: float | None = None
    max_open_positions: int | None = None
    max_slippage_points: int | None = None
    max_spread: dict[str, float] | None = None
    allowed_symbols: list[str] | None = None
    dead_man_seconds: int | None = None
    pending_max_minutes: int | None = None


class AgentLiveView(DomainModel):
    login: str
    agent_id: str
    agent_version: str
    mode: str
    mode_ceiling: str | None = None
    identity: str | None = None
    heartbeat_age_s: float | None = None
    registered_since: datetime | None = None
    capabilities: list[str] = Field(default_factory=list)
    attached_experts: list[str] = Field(default_factory=list)
    halted: bool | None = None
    tradable: bool | None = None
    core_silent_ms: int | None = None
    server: str | None = None
    protocol_version: int | None = None
    chart_symbol: str | None = None
    chart_period: str | None = None
    instance_id: str | None = None
    terminal_build: int | None = None
    init_state: str | None = None
    init_issues: list[str] = Field(default_factory=list)
    local_protections: ProtectionsView | None = None


class ConditionView(DomainModel):
    code: str
    label: str
    light: str  # GREEN / RED / PENDING
    detail: str
    reason_codes: list[str] = Field(default_factory=list)


class AuthorizationView(DomainModel):
    allowed: bool
    reasons: list[str] = Field(default_factory=list)


class ReadinessView(DomainModel):
    """The reading of the conditions of ``shared/ea_readiness.py``: technical readiness, and — as a separate line — whether an order could be placed."""

    verdict: str  # READY / VALIDATING / BLOCKED
    header_code: str | None = None
    red_codes: list[str] = Field(default_factory=list)
    pending_codes: list[str] = Field(default_factory=list)
    warning_codes: list[str] = Field(default_factory=list)
    conditions: list[ConditionView] = Field(default_factory=list)
    execution_authorization: AuthorizationView


class Mt5TerminalView(DomainModel):
    terminal: RegisteredTerminal
    hello_received: bool
    agent: AgentLiveView | None = None
    readiness: ReadinessView


class LauncherEventView(DomainModel):
    occurred_at: datetime | None = None
    type: str
    severity: str = "INFO"
    instance_id: str | None = None
    diagnostic: str = ""


class SystemCenterView(DomainModel):
    observed_at: datetime
    core_status: str
    execution_mode: str
    agents_connected: int
    mt5_workers_alive: int
    terminals: list[Mt5TerminalView] = Field(default_factory=list)
    unregistered_agents: list[AgentLiveView] = Field(default_factory=list)
    registry_problem: str | None = None
    recent_events: list[LauncherEventView] = Field(default_factory=list)
