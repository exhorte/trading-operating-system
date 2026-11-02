"""Autonomy: the ladder a human climbs one rung at a time, the lease he renews, the brake he pulls.

Every gesture here is a *person's* (the cockpit button); nothing in the core arms by itself, and nothing here sends an order. The
state machine and its refusals live in ``domain/autonomy/state.py`` — the routes only carry the gesture in and the answer out.
"""

from __future__ import annotations

from fastapi import APIRouter

from trading_os.api.schemas.autonomy import ArmRequest, DisarmRequest, HaltRequest, HaltResult
from trading_os.app.dependencies import Core
from trading_os.domain.autonomy.overview import AutonomyOverview
from trading_os.domain.autonomy.promotion import PromotionReport
from trading_os.domain.autonomy.state import AutonomyState
from trading_os.shared.errors import TradingOsError

router = APIRouter(prefix="/api/autonomy", tags=["autonomy"])


@router.get("/state", response_model=AutonomyOverview, summary="Mode, ceiling, lease, readiness")
async def state(c: Core) -> AutonomyOverview:
    return await c.autonomy.overview()


@router.get(
    "/promotion",
    response_model=PromotionReport,
    summary="What has been done and measured before asking for more autonomy — advisory, it blocks nothing (ADR 0027)",
)
async def promotion(c: Core) -> PromotionReport:
    return await c.promotion.report(c.accounts.active_account_id)


@router.post(
    "/arm", response_model=AutonomyState,
    summary="Climb one rung. The automatic rungs need a green readiness evaluated for this very call",
)  # fmt: skip
async def arm(body: ArmRequest, c: Core) -> AutonomyState:
    return await c.autonomy.arm(body.target)


@router.post(
    "/renew", response_model=AutonomyState, summary="Renew the ARMED window (30 minutes), readiness permitting"
)
async def renew(c: Core) -> AutonomyState:
    return await c.autonomy.renew()


@router.post("/disarm", response_model=AutonomyState, summary="Step down — always allowed, immediate")
async def disarm(body: DisarmRequest, c: Core) -> AutonomyState:
    return await c.autonomy.disarm(body.target, acknowledge=body.acknowledge, reason=body.reason)


@router.post(
    "/halt", response_model=HaltResult,
    summary="Emergency stop: cut the state, the entries and the execution agent's kill switch, and lock the active account",
)  # fmt: skip
async def halt(body: HaltRequest, c: Core) -> HaltResult:
    halted = await c.autonomy.halt(body.reason, actor="user")
    lockout = None
    warnings: list[str] = []
    account_id = c.accounts.active_account_id
    if account_id is not None:
        try:
            lockout = await c.risk.engage_kill_switch(account_id)
        except TradingOsError as error:  # the database is down, say: the halt stands, the record is missing — say so
            warnings.append(f"the kill-switch lockout could not be recorded: {error.safe_message}")
    return HaltResult(state=halted, kill_switch=lockout, warnings=warnings)
