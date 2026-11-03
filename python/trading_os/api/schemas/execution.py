"""The execution routes' models."""

from __future__ import annotations

from datetime import datetime

from pydantic import ConfigDict, Field

from trading_os.api.schemas.common import StrictRequest
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


class CloseAllRequest(StrictRequest):
    """The body of ``POST /api/execution/close-all`` (ADR 0034). Closing is a human gesture and the body says so in so many words:
    ``confirmation`` must be ``CLOSE_ALL`` (opening the dialog sends nothing), ``positionIds`` are the positions the trader saw in the
    preview — a position opened since is not closed, only reported — and the pending orders are cancelled only if asked for."""

    account_id: AccountId
    batch_id: str = Field(
        min_length=6, max_length=24, description="From the preview. Calling again with the same id changes nothing."
    )
    position_ids: list[str] = Field(default_factory=list, max_length=200)
    include_pending_orders: bool = False
    order_ids: list[str] = Field(default_factory=list, max_length=200)
    confirmation: str
