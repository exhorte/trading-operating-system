"""The events of the Trading OS (mission § 32). One pydantic model per event: the same class feeds the audit table, the
WebSocket frame and — through the OpenAPI/JSON Schema — the cockpit's TypeScript types. No distributed bus: the services
publish on an in-process dispatcher.

``persist = False`` marks high-rate telemetry (ticks, heartbeats, snapshots, evaluation chatter): broadcast to the cockpit,
not appended to the audit trail (the facts they summarise have their own tables).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from trading_os.domain.accounts.anti_tilt import GuardReason
from trading_os.domain.accounts.models import AccountSnapshot, Environment
from trading_os.domain.autonomy.readiness import ReadinessReport
from trading_os.domain.autonomy.state import AutonomyMode
from trading_os.domain.execution.agent import AgentStatus
from trading_os.domain.execution.commands import ExecutionCommand
from trading_os.domain.market.calendar import UpcomingRelease
from trading_os.domain.market.models import Candle, Tick
from trading_os.domain.positions.models import ClosedTrade, Position
from trading_os.domain.positions.reconciliation import Mismatch
from trading_os.domain.primitives import Side
from trading_os.domain.risk.decision import RiskDecision
from trading_os.domain.risk.view import RiskStatus
from trading_os.domain.strategy.intent import TradeIntent
from trading_os.domain.system.incidents import Incident
from trading_os.domain.system.supervision import Finding, Severity
from trading_os.shared.events.base import Event

# ------------------------------------------------------------------------------------------------------ accounts


class AccountCreated(Event):
    wire_type = "account.created"
    name: str
    provider: str
    environment: Environment


class AccountUpdated(Event):
    wire_type = "account.updated"
    fields: list[str]


class AccountArchived(Event):
    wire_type = "account.archived"


class AccountTradingToggled(Event):
    """The user's « Enable / Disable Trading » switch for one account."""

    wire_type = "account.trading_toggled"
    enabled: bool


class AccountConnected(Event):
    wire_type = "account.connected"
    server: str
    currency: str
    environment: Environment


class AccountDisconnected(Event):
    wire_type = "account.disconnected"
    reason: str


class AccountErrored(Event):
    wire_type = "account.error"
    code: str
    detail: str


class ActiveAccountChanged(Event):
    wire_type = "account.active_changed"
    previous: str | None
    current: str | None


class AccountSnapshotUpdated(Event):
    wire_type = "account.snapshot"
    persist = False
    snapshot: AccountSnapshot


class AccountRulesChanged(Event):
    wire_type = "account.rules_changed"
    version_id: str
    deferred: bool
    reasons: list[GuardReason]


# ------------------------------------------------------------------------------------------------------ market


class MarketTickReceived(Event):
    wire_type = "market.tick"
    persist = False
    tick: Tick


class CandleClosed(Event):
    wire_type = "market.candle_closed"
    persist = False
    candle: Candle


class MarketCalendarUpdated(Event):
    wire_type = "market.calendar_updated"
    releases: list[UpcomingRelease] | None  # None = unknown: the news gate is closed
    synced_at: datetime | None


# ------------------------------------------------------------------------------------------------------ positions


class PositionsSnapshotUpdated(Event):
    wire_type = "positions.snapshot"
    persist = False
    positions: list[Position]


class PositionOpened(Event):
    wire_type = "position.opened"
    position_id: str
    symbol: str
    side: Side
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    opened_at: datetime
    reconstructed: bool = False  # seen only in deal history (opened and closed between two polls)


class PositionModified(Event):
    wire_type = "position.modified"
    position_id: str
    field: Literal["volume", "stop_loss", "take_profit"]
    previous: float
    current: float


class PositionClosed(Event):
    wire_type = "position.closed"
    trade: ClosedTrade


# ------------------------------------------------------------------------------------------------------ strategy


class StrategyEvaluationStarted(Event):
    wire_type = "strategy.evaluation_started"
    persist = False
    strategy_id: str
    symbol: str


class StrategyEvaluationCompleted(Event):
    wire_type = "strategy.evaluation_completed"
    persist = False
    strategy_id: str
    symbol: str
    outcome: Literal["proposed", "blocked"]
    stage: str | None = None
    detail: str | None = None
    event_at: datetime


class TradeIntentCreated(Event):
    wire_type = "trade.intent_created"
    intent: TradeIntent


class TradeRejected(Event):
    wire_type = "trade.rejected"
    intent_id: str
    stage: Literal["risk", "execution"]
    reasons: list[str]


# ------------------------------------------------------------------------------------------------------ risk


class RiskEvaluationStarted(Event):
    wire_type = "risk.evaluation_started"
    persist = False
    intent_id: str | None = None


class RiskApproved(Event):
    wire_type = "risk.approved"
    decision: RiskDecision


class RiskRejected(Event):
    wire_type = "risk.rejected"
    decision: RiskDecision


class RiskStateUpdated(Event):
    wire_type = "risk.state_updated"
    persist = False
    risk: RiskStatus


class LockoutEnabled(Event):
    wire_type = "risk.lockout_enabled"
    lockout_id: str
    reason: str
    since: datetime
    until: datetime | None = None


class LockoutCleared(Event):
    wire_type = "risk.lockout_cleared"
    lockout_id: str | None
    cleared_by: str


class LockoutAcknowledged(Event):
    wire_type = "risk.lockout_acknowledged"
    lockout_id: str
    acknowledged_at: datetime


class LockoutViolated(Event):
    """A position opened while a lockout was active (T02c): flagged the instant it is seen."""

    wire_type = "risk.lockout_violated"
    broker_position_id: str
    symbol: str
    side: Side
    lockout_id: str
    lockout_reason: str
    opened_at: datetime


# ------------------------------------------------------------------------------------------------------ execution


class ExecutionCommandCreated(Event):
    wire_type = "execution.command_created"
    command: ExecutionCommand


class ExecutionCommandSent(Event):
    wire_type = "execution.command_sent"
    command_id: str
    login_hint: str | None = None  # never the login itself: the agent's id


class ExecutionAcknowledged(Event):
    wire_type = "execution.acknowledged"
    command_id: str
    status: Literal["ACCEPTED", "REJECTED", "DUPLICATE", "EXPIRED"]
    reason: str | None = None


class ExecutionRejected(Event):
    """Refused before any broker call: validation, risk, mode, or the agent's local barriers."""

    wire_type = "execution.rejected"
    command_id: str
    code: str
    detail: str


class ExecutionReported(Event):
    """The final result: executed at the broker, or simulated (paper broker / agent compiled OBSERVE)."""

    wire_type = "execution.reported"
    command_id: str
    outcome: Literal["executed", "simulated"]
    symbol: str
    side: Side | None = None
    filled_volume: float | None = None
    average_price: float | None = None
    broker_order_id: str | None = None
    broker_position_id: str | None = None
    detail: str = ""
    replayed: bool = False


class ExecutionFailed(Event):
    wire_type = "execution.failed"
    command_id: str
    detail: str
    broker_retcode: str | None = None


class ExecutionUnknown(Event):
    """The outcome could not be observed. Never replayed: reconciliation decides."""

    wire_type = "execution.unknown"
    command_id: str
    detail: str


class CommandReconciled(Event):
    """An in-doubt command was settled from what the broker shows — by the execution agent or by the core itself.
    Inconclusive attempts (« not found yet ») are not events: the command simply stays RECONCILING."""

    wire_type = "execution.reconciled"
    command_id: str
    outcome: Literal["executed", "rejected"]
    source: Literal["agent", "core"]
    broker_order_id: str | None = None
    broker_position_id: str | None = None
    filled_volume: float | None = None
    average_price: float | None = None
    detail: str = ""


# ------------------------------------------------------------------------------------------------------ agent link


class AgentConnected(Event):
    wire_type = "agent.connected"
    status: AgentStatus


class AgentDisconnected(Event):
    wire_type = "agent.disconnected"
    agent_login: str


class AgentStatusChanged(Event):
    wire_type = "agent.status_changed"
    status: AgentStatus


class AgentHeartbeatReceived(Event):
    wire_type = "agent.heartbeat"
    persist = False
    agent_id: str
    latency_ms: float


# ------------------------------------------------------------------------------------------------------ reconciliation


class ReconciliationStarted(Event):
    wire_type = "reconciliation.started"
    persist = False


class ReconciliationMismatch(Event):
    wire_type = "reconciliation.mismatch"
    mismatch: Mismatch


class ReconciliationCompleted(Event):
    wire_type = "reconciliation.completed"
    persist = False
    mismatches: int
    critical: int
    positions_checked: int
    readable: bool = True  # False: MT5 or the database could not be read, nothing was concluded


# ------------------------------------------------------------------------------------------------------ autonomy


class AutonomyModeChanged(Event):
    wire_type = "autonomy.mode_changed"
    previous: AutonomyMode
    current: AutonomyMode
    reason: str
    lease_until: datetime | None = None


class AutonomyArmed(Event):
    wire_type = "autonomy.armed"
    mode: AutonomyMode
    lease_until: datetime | None = None
    readiness: ReadinessReport | None = None


class AutonomyDisarmed(Event):
    wire_type = "autonomy.disarmed"
    mode: AutonomyMode
    reason: str


class AutonomyHalted(Event):
    wire_type = "autonomy.halted"
    reason: str


# ------------------------------------------------------------------------------------------------------ system


class SystemHeartbeat(Event):
    wire_type = "system.heartbeat"
    persist = False
    seq: int
    uptime_seconds: float


class HeartbeatMissed(Event):
    wire_type = "system.heartbeat_missed"
    component: str
    age_seconds: float | None


class SystemHealthChanged(Event):
    wire_type = "system.health_changed"
    status: Severity
    findings: list[Finding]


class IncidentOpened(Event):
    wire_type = "system.incident_opened"
    incident: Incident


class IncidentResolved(Event):
    wire_type = "system.incident_resolved"
    incident: Incident
