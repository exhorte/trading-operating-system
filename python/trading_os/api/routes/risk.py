"""Risk: the single control point before execution (ADR 0007), as the cockpit sees it.

Reading is free (state, ``can-i-trade``, the decisions on record, the lockout ledger). Two gestures write: reviewing a trade
(``POST /evaluate`` — the decision is persisted before it is returned) and the lockout ledger (the manual kill switch, and the
human's acknowledgement). A timed pause ends by itself and cannot be acknowledged; an untimed lockout only a person clears.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Response

from trading_os.api.params import AccountQuery, Limit, resolve_account
from trading_os.api.schemas.risk import AccountRequest, AcknowledgeResult, LockoutOverview, ReviewRequest
from trading_os.app.dependencies import Core
from trading_os.domain.risk.decision import CanITradeResult, RiskDecision
from trading_os.domain.risk.lockout import ActiveLockout
from trading_os.domain.risk.view import RiskStatus
from trading_os.domain.strategy.intent import TradeIntent
from trading_os.shared.errors import NotFound
from trading_os.shared.ids import new_id

router = APIRouter(prefix="/api/risk", tags=["risk"])

SymbolQuery = Annotated[str | None, Query(pattern=r"^[A-Za-z0-9._#+\-]{1,32}$")]


@router.get("/state", response_model=RiskStatus, summary="The account's risk gates, drawdown, exposure and lockout")
async def state(c: Core, account_id: AccountQuery = None) -> RiskStatus:
    account_id = await resolve_account(c, account_id)
    status = c.risk.status(account_id)
    if status is None:
        raise NotFound(
            "no risk state yet: the account is not connected, or the first evaluation has not run", code="no_risk_state"
        )
    return status


@router.get("/can-i-trade", response_model=CanITradeResult, summary="ALLOWED or DENIED right now, with every reason")
async def can_i_trade(c: Core, account_id: AccountQuery = None, symbol: SymbolQuery = None) -> CanITradeResult:
    return await c.risk.can_i_trade(await resolve_account(c, account_id), symbol)


@router.post(
    "/evaluate", response_model=RiskDecision, status_code=201,
    summary="Review a trade: approved with a size, or refused with every reason. The decision is recorded either way",
)  # fmt: skip
async def evaluate(body: ReviewRequest, c: Core) -> RiskDecision:
    account_id = await resolve_account(c, body.account_id)
    now = c.clock.now()
    intent = TradeIntent(
        intent_id=body.intent_id or new_id("intent"),
        account_id=account_id,
        strategy_id=body.strategy_id,
        strategy_version=body.strategy_version,
        symbol=body.symbol,
        side=body.side,
        order_type=body.order_type,
        entry_price=body.entry_price,
        stop_loss=body.stop_loss,
        take_profit=body.take_profit,
        created_at=now,
        expires_at=now + timedelta(seconds=body.valid_for_seconds),
        rationale=body.rationale,
    )
    return await c.risk.review(intent)


@router.get("/decisions", response_model=list[RiskDecision], summary="The decisions on record, newest first")
async def decisions(c: Core, account_id: AccountQuery = None, limit: Limit = 50) -> list[RiskDecision]:
    return await c.repos.risk.recent_decisions(await resolve_account(c, account_id), limit)


@router.get("/decisions/{decision_id}", response_model=RiskDecision)
async def decision(decision_id: str, c: Core) -> RiskDecision:
    found = await c.repos.risk.get_decision(decision_id)
    if found is None:
        raise NotFound(f"no risk decision {decision_id!r}", code="decision_not_found")
    return found


@router.get("/lockouts", response_model=LockoutOverview, summary="The lockout in force and the ledger")
async def lockouts(
    c: Core, account_id: AccountQuery = None, up_to: Annotated[datetime | None, Query(alias="upTo")] = None
) -> LockoutOverview:
    account_id = await resolve_account(c, account_id)
    now = c.clock.now()
    return LockoutOverview(
        active=await c.repos.risk.active_lockout(account_id, now),
        history=await c.repos.risk.lockout_history(account_id, up_to or now),
    )


@router.post(
    "/lockouts", response_model=ActiveLockout, status_code=201,
    responses={200: {"model": ActiveLockout, "description": "The kill switch was already engaged: the existing lockout."}},
    summary="Engage the manual kill switch (idempotent: engaged twice is engaged once)",
)  # fmt: skip
async def engage_kill_switch(body: AccountRequest, c: Core, response: Response) -> ActiveLockout:
    account_id = await resolve_account(c, body.account_id)
    before = await c.repos.risk.active_lockout(account_id, c.clock.now())
    lockout = await c.risk.engage_kill_switch(account_id)
    if before is not None and before.lockout_id == lockout.lockout_id:
        response.status_code = 200
    return lockout


@router.post(
    "/lockouts/{lockout_id}/acknowledge", response_model=AcknowledgeResult,
    summary="The human saw it: clear an untimed lockout (a timed pause ends by itself)",
)  # fmt: skip
async def acknowledge(lockout_id: str, body: AccountRequest, c: Core) -> AcknowledgeResult:
    account_id = await resolve_account(c, body.account_id)
    active = await c.repos.risk.active_lockout(account_id, c.clock.now())
    if active is None or active.lockout_id != lockout_id:
        raise NotFound(f"lockout {lockout_id!r} is not the active lockout of this account", code="lockout_not_active")
    return AcknowledgeResult(lockout_id=await c.risk.acknowledge(account_id))
