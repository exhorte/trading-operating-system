"""The execution routes' models."""

from __future__ import annotations

from datetime import datetime

from pydantic import ConfigDict

from trading_os.domain.autonomy.state import AutonomyMode, ExecutionRoute
from trading_os.domain.execution.agent import AgentStatus
from trading_os.domain.execution.commands import ExecutionCommand, ExecutionRequest
from trading_os.domain.positions.reconciliation import ReconciliationReport
from trading_os.domain.primitives import AccountId, DomainModel


class CommandRequest(ExecutionRequest):
    """The body of ``POST /api/execution/commands``: an ``ExecutionRequest``, strict about unknown fields — a misspelt
    ``stopLoss`` or ``positionId`` must be refused, not dropped."""

    model_config = ConfigDict(extra="forbid")


class ExecutionState(DomainModel):
    """Everything the cockpit needs to know about executing on one account, in one read."""

    account_id: AccountId
    mode: AutonomyMode  # what the account is really in: the system's state under the account's own ceiling
    route: ExecutionRoute  # what happens to an approved order in that mode
    agent: AgentStatus | None  # the EA attached to this account's terminal, if any
    agent_last_heartbeat_at: datetime | None = None
    in_doubt: list[ExecutionCommand]  # sent and not yet settled — they block disconnecting and switching away
    recent: list[ExecutionCommand]
    reconciliation: ReconciliationReport | None = None  # the last run, readable or not
