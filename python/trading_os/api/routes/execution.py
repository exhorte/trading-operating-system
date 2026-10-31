"""Execution: commands and what became of them.

A command is the only way an order exists, and it exists first as a *row*: persisted before anything is sent, identified by the
caller's ``commandId`` (one id, at most one execution — a replay returns the original). Its fate is the engine's, not the
route's: a refusal is not an HTTP error but an **outcome** (``rejections`` + a ``REJECTED`` command on record, so the audit
trail holds what was asked and why it was not done). What the engine accepts depends on the mode the account is really in
(``GET /state``): in OFF/OBSERVE it is recorded only, in PAPER simulated, in CONFIRM and above it goes to the EA — which, while
it is compiled in OBSERVE, still executes nothing.

The reconciliation endpoints are the other half: they compare the database's beliefs with what the broker shows.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Response

from trading_os.api.params import AccountQuery, Limit, resolve_account
from trading_os.api.schemas.execution import CommandRequest, ExecutionState
from trading_os.app.dependencies import Core
from trading_os.domain.autonomy.state import route_for
from trading_os.domain.execution.commands import ExecutionCommand, ExecutionRequest
from trading_os.domain.positions.reconciliation import ReconciliationReport
from trading_os.services.execution import ExecutionOutcome
from trading_os.shared.errors import NotFound

router = APIRouter(prefix="/api/execution", tags=["execution"])

RECENT_COMMANDS = 20


@router.get(
    "/state", response_model=ExecutionState, summary="Mode, route, agent, commands in doubt, last reconciliation"
)
async def state(c: Core, account_id: AccountQuery = None) -> ExecutionState:
    account_id = await resolve_account(c, account_id)
    account = await c.accounts.effective(account_id)
    mode = c.autonomy.effective_mode(account)
    login = str(account.login)
    return ExecutionState(
        account_id=account_id,
        mode=mode,
        route=route_for(mode),
        agent=c.execution.agent_status(login),
        agent_last_heartbeat_at=c.execution.last_heartbeat(login),
        in_doubt=await c.execution.in_doubt(account_id),
        recent=await c.execution.recent(account_id, RECENT_COMMANDS),
        reconciliation=c.reconciliation.report(account_id),
    )


@router.get("/commands", response_model=list[ExecutionCommand], summary="The commands on record, newest first")
async def commands(
    c: Core,
    account_id: AccountQuery = None,
    limit: Limit = 50,
    in_doubt: Annotated[bool, Query(alias="inDoubt", description="Only those sent and not yet settled.")] = False,
) -> list[ExecutionCommand]:
    account_id = await resolve_account(c, account_id)
    return await c.execution.in_doubt(account_id) if in_doubt else await c.execution.recent(account_id, limit)


@router.get("/commands/{command_id}", response_model=ExecutionCommand)
async def command(command_id: str, c: Core) -> ExecutionCommand:
    found = await c.execution.get(command_id)
    if found is None:
        raise NotFound(f"unknown command {command_id!r}", code="command_not_found")
    return found


@router.post(
    "/commands", response_model=ExecutionOutcome, status_code=201,
    responses={200: {"model": ExecutionOutcome, "description": "The same commandId was submitted before: the original."}},
    summary="Submit a command. 201 = recorded (possibly REJECTED, with the reasons); 200 = a replay of an earlier one",
)  # fmt: skip
async def submit(body: CommandRequest, c: Core, response: Response) -> ExecutionOutcome:
    """A human gesture: in CONFIRM mode it is itself the confirmation. An OPEN needs a risk decision that approved this very
    trade (``POST /api/risk/evaluate``) — the engine checks symbol, side, volume and stop against it."""
    outcome = await c.execution.submit(ExecutionRequest.model_validate(body.model_dump()))
    if outcome.replayed:
        response.status_code = 200
    return outcome


@router.post(
    "/commands/{command_id}/confirm", response_model=ExecutionOutcome,
    summary="Confirm a PENDING command (CONFIRM mode); everything is checked again against the world as it is now",
)  # fmt: skip
async def confirm(command_id: str, c: Core) -> ExecutionOutcome:
    return await c.execution.confirm(command_id)


@router.post(
    "/commands/{command_id}/cancel", response_model=ExecutionCommand,
    summary="Withdraw a PENDING command; one already sent can no longer be cancelled",
)  # fmt: skip
async def cancel(command_id: str, c: Core) -> ExecutionCommand:
    return await c.execution.cancel(command_id)


@router.get(
    "/reconciliation", response_model=ReconciliationReport,
    summary="What the last comparison of the database with the broker found",
)  # fmt: skip
async def reconciliation(c: Core, account_id: AccountQuery = None) -> ReconciliationReport:
    account_id = await resolve_account(c, account_id)
    report = c.reconciliation.report(account_id)
    if report is None:
        raise NotFound("no reconciliation has run yet for this account", code="no_reconciliation")
    return report


@router.post(
    "/reconciliation/run", response_model=ReconciliationReport,
    summary="Compare now. Read-only on the broker; it settles commands in doubt from the broker's own history",
)  # fmt: skip
async def run_reconciliation(c: Core, account_id: AccountQuery = None) -> ReconciliationReport:
    return await c.reconciliation.reconcile(await resolve_account(c, account_id))
