"""Strategy: what S01 saw, what it proposed, what became of it, and how well that agrees with what was actually traded.

Read-only. The strategy decides nothing here: an evaluation is a measurement (ADR 0011), an intent is what a proposal turned into on its
way to the Risk Engine, and the agreement view compares proposals with the positions that were really taken — agreement, never
performance. Every figure is recorded by ``StrategyService`` as it happens; these routes only read it back.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from trading_os.api.params import AccountQuery, Limit, resolve_account
from trading_os.app.dependencies import Core
from trading_os.domain.strategy.evaluation import StrategyEvaluation
from trading_os.domain.strategy.intent import TradeIntent
from trading_os.domain.strategy.s01.reconciliation import AgreementProposal, AgreementRow, AgreementTrade, reconcile
from trading_os.shared.errors import ValidationFailed

router = APIRouter(prefix="/api/strategy", tags=["strategy"])

DEFAULT_LOOKBACK = timedelta(hours=24)
MAX_LOOKBACK = timedelta(days=31)
Since = Annotated[datetime | None, Query(description="Default: the last 24 hours. At most 31 days back.")]


def _since(now: datetime, since: datetime | None) -> datetime:
    start = since or now - DEFAULT_LOOKBACK
    if now - start > MAX_LOOKBACK:
        raise ValidationFailed("since cannot be more than 31 days back", code="window_too_wide")
    return start


@router.get(
    "/proposals", response_model=list[StrategyEvaluation],
    summary="Every strategy evaluation (S01, S02) since a time, newest first — proposed ones and the stage where the others stopped",
)  # fmt: skip
async def proposals(
    c: Core,
    since: Since = None,
    status: Annotated[Literal["proposed", "blocked"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 1000,
) -> list[StrategyEvaluation]:
    found = await c.repos.strategy.evaluations_since(_since(c.clock.now(), since))
    return [e for e in found if status is None or e.status == status][:limit]


@router.get(
    "/intents", response_model=list[TradeIntent], summary="What proposals became on their way to the Risk Engine"
)
async def intents(c: Core, account_id: AccountQuery = None, limit: Limit = 50) -> list[TradeIntent]:
    return await c.repos.strategy.recent_intents(await resolve_account(c, account_id), limit)


@router.get(
    "/agreement", response_model=list[AgreementRow],
    summary="Proposed-and-taken, proposed-and-refused, taken-without-proposal — within a tolerance of the proposal's time",
)  # fmt: skip
async def agreement(
    c: Core,
    account_id: AccountQuery = None,
    since: Since = None,
    tolerance_minutes: Annotated[float, Query(alias="toleranceMinutes", gt=0, le=120)] = 5.0,
) -> list[AgreementRow]:
    """« Un trade pris trois minutes après une proposition sur le même niveau est le même trade ». Positions still open count as
    trades; a closed trade whose opening time is not on record cannot be matched by time and is left out."""
    account_id = await resolve_account(c, account_id)
    now = c.clock.now()
    start = _since(now, since)
    proposed = [
        AgreementProposal(symbol=e.symbol, side=e.side, detected_at=e.event_at)
        for e in await c.repos.strategy.evaluations_since(start)
        if e.status == "proposed"
        and e.side is not None
        and e.strategy_id == "S01"  # EA-02 measures S01 against the trader
    ]
    trades = [
        AgreementTrade(broker_position_id=t.broker_position_id, symbol=t.symbol, side=t.side, opened_at=t.opened_at)
        for t in await c.repos.positions.journal_trades(account_id, start, now)
        if t.opened_at is not None
    ]
    seen = {t.broker_position_id for t in trades}
    trades += [
        AgreementTrade(broker_position_id=p.position_id, symbol=p.symbol, side=p.side, opened_at=p.opened_at)
        for p in c.positions.positions(account_id)
        if p.opened_at is not None and p.opened_at >= start and p.position_id not in seen
    ]
    return reconcile(proposed, trades, tolerance_minutes)
