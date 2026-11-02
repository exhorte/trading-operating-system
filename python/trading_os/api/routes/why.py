"""Why no trade: the reasons the core already states, in one order and one sentence (ADR 0028). Read-only."""

from __future__ import annotations

from fastapi import APIRouter

from trading_os.app.dependencies import Core
from trading_os.domain.autonomy.why import WhyNoTrade

router = APIRouter(prefix="/api/why-no-trade", tags=["autonomy"])


@router.get(
    "", response_model=WhyNoTrade,
    summary="Why the system is not taking a trade right now: mode, guardian, risk gates, readiness, where each strategy stopped",
)  # fmt: skip
async def why_no_trade(c: Core) -> WhyNoTrade:
    return await c.why.answer()
