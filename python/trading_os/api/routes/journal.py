"""Journal: the closed trades, how well they respected the rules, and the file of one position.

Judged on the server (T05/T07): the R multiple and the rules each trade broke are computed against the lockout ledger and the
account's rules *as they were*, so the cockpit shows the verdict instead of recomputing it. A window defaults to the last 30
days and cannot exceed a year.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Path

from trading_os.api.params import AccountQuery, resolve_account, resolve_window
from trading_os.api.schemas.journal import TradeCaptures
from trading_os.app.dependencies import Core
from trading_os.domain.journal.models import ComplianceSummary, JournalTradeView, TradeFile
from trading_os.shared.errors import NotFound

router = APIRouter(prefix="/api/journal", tags=["journal"])

PositionId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_\-]{1,40}$", description="The broker's POSITION_IDENTIFIER.")]


@router.get("/trades", response_model=list[JournalTradeView], summary="Closed trades in the window, newest first")
async def trades(
    c: Core, account_id: AccountQuery = None, start: datetime | None = None, end: datetime | None = None
) -> list[JournalTradeView]:
    account_id = await resolve_account(c, account_id)
    start, end = resolve_window(c.clock.now(), start, end)
    return await c.journal.trades(account_id, start, end)


@router.get("/compliance", response_model=ComplianceSummary, summary="How the window's trades respected the rules")
async def compliance(
    c: Core, account_id: AccountQuery = None, start: datetime | None = None, end: datetime | None = None
) -> ComplianceSummary:
    account_id = await resolve_account(c, account_id)
    start, end = resolve_window(c.clock.now(), start, end)
    return await c.journal.compliance(account_id, start, end)


@router.get("/trades/{broker_position_id}", response_model=TradeFile, summary="One position, reconstructed")
async def trade_file(broker_position_id: PositionId, c: Core, account_id: AccountQuery = None) -> TradeFile:
    return await c.journal.trade_file(await resolve_account(c, account_id), broker_position_id)


@router.get(
    "/captures/{broker_position_id}", response_model=TradeCaptures, summary="The entry and exit captures of a position"
)
async def captures(broker_position_id: PositionId, c: Core, account_id: AccountQuery = None) -> TradeCaptures:
    entry, exit_ = await c.journal.captures(await resolve_account(c, account_id), broker_position_id)
    if entry is None and exit_ is None:
        raise NotFound(f"no capture for position {broker_position_id}", code="capture_not_found")
    return TradeCaptures(entry=entry, exit=exit_)
