"""The shape of the first frame of every WebSocket (``system.snapshot``): the whole state the cockpit draws, in one piece.

A model rather than a dictionary so that the cockpit's TypeScript type for it is generated from the same definition as the REST
responses — the stream and the API describe one account, one position, one risk status, in the same words.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from trading_os.domain.accounts.models import Account, AccountSnapshot
from trading_os.domain.autonomy.overview import AutonomyOverview
from trading_os.domain.execution.agent import AgentStatus
from trading_os.domain.execution.commands import ExecutionCommand
from trading_os.domain.market.calendar import CalendarSnapshot
from trading_os.domain.market.models import Tick
from trading_os.domain.positions.models import PendingOrder, Position
from trading_os.domain.primitives import DomainModel
from trading_os.domain.risk.view import RiskStatus
from trading_os.domain.system.supervision import Finding, Severity


class AccountState(DomainModel):
    """What the core holds in memory about one connected account."""

    snapshot: AccountSnapshot | None
    positions: list[Position]
    orders: list[PendingOrder]
    quotes: list[Tick]
    risk: RiskStatus | None
    agent: AgentStatus | None  # the execution agent attached to this account's terminal, if any
    commands: list[ExecutionCommand]  # the most recent ones, newest first


class HealthDigest(DomainModel):
    status: Severity
    findings: list[Finding]
    checked_at: datetime | None  # the supervisor's last look; None = it has not run yet


class CockpitSnapshot(DomainModel):
    server_time: datetime
    version: str
    active_account_id: str | None
    accounts: list[Account]
    autonomy: AutonomyOverview
    health: HealthDigest
    calendar: CalendarSnapshot
    account_states: dict[str, AccountState] = Field(default_factory=dict)  # by account id, connected accounts only
