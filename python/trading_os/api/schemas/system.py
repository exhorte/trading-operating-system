"""The system routes' models: health (open, minimal), status (guarded, the cockpit's overview), the audit trail, incidents."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from trading_os.api.schemas.common import StrictRequest
from trading_os.domain.accounts.models import Account
from trading_os.domain.autonomy.overview import AutonomyOverview
from trading_os.domain.autonomy.plan_modes import PlanMode
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.execution.agent import AgentStatus
from trading_os.domain.primitives import DomainModel
from trading_os.domain.system.supervision import Finding, Severity


class DatabaseView(DomainModel):
    up: bool
    last_error: str | None = None
    last_ok_at: datetime | None = None
    last_error_at: datetime | None = None


class JobView(DomainModel):
    name: str
    interval_s: float
    critical: bool
    runs: int
    failures: int
    consecutive_failures: int
    running: bool
    overdue: bool
    last_success_at: datetime | None = None
    last_duration_ms: float | None = None
    last_error: str | None = None


class AuditView(DomainModel):
    written: int
    lost: int  # events that could not be recorded: a gap in the audit trail, counted rather than hidden


class TickQueueView(DomainModel):
    queued: int
    written: int
    dropped: int  # quotes the database could not take: telemetry may be lossy, never silently


class WebSocketView(DomainModel):
    clients: int
    frames_sent: int
    frames_dropped: int
    closed_for_overflow: int


class AccessView(DomainModel):
    """Whether each door is guarded — never the secret that guards it."""

    cockpit_guarded: bool  # the HTTP/WebSocket API demands the cockpit's credential
    agent_link_guarded: bool  # the EA's socket demands the agent's credential


class SystemHealthView(DomainModel):
    status: Severity
    version: str
    started_at: datetime
    uptime_seconds: float
    checked_at: datetime | None = None  # the supervisor's last look; None = it has not run yet
    database: DatabaseView
    audit: AuditView
    ticks: TickQueueView
    websocket: WebSocketView
    agents_connected: int
    jobs: list[JobView]
    findings: list[Finding]
    access: AccessView


class SystemStatus(DomainModel):
    server_time: datetime
    version: str
    active_account_id: str | None = None
    accounts: list[Account]
    agents: list[AgentStatus]
    autonomy: AutonomyOverview
    health: SystemHealthView


class EventRecord(DomainModel):
    event_id: str
    type: str
    occurred_at: datetime
    account_id: str | None = None
    correlation_id: str | None = None
    payload: dict[str, Any]


class StartRequest(StrictRequest):
    """« Démarrer le système » (ADR 0034). Starting climbs to ``target`` (OBSERVE by default; PAPER or CONFIRM when asked) and never
    higher; a real account needs ``acknowledgeRealAccount`` to start up to CONFIRM."""

    target: AutonomyMode = AutonomyMode.OBSERVE
    acknowledge_real_account: bool = False


class AuthorizeAutomaticRequest(StrictRequest):
    """« Autoriser le trading automatique »: a separate gesture from starting, one rung, with every condition green at that instant."""

    acknowledge_real_account: bool = False


class AuthorizeAutomaticResult(DomainModel):
    mode: AutonomyMode
    plan_mode: PlanMode
