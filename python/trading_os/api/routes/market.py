"""Market: quotes, specifications, candles and the news calendar — read-only, from the account's own terminal.

Nothing is invented here and nothing is cached by the route: quotes and specifications are what the market-data service already
holds; candles are read through the read-only MT5 worker on demand; the calendar is the news service's last sync (``releases:
null`` means *unknown*, never « nothing scheduled »).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query

from trading_os.api.params import AccountQuery, resolve_account
from trading_os.api.schemas.market import MarketQuote
from trading_os.app.dependencies import Core
from trading_os.domain.market.analysis import MarketContextState, analyze_market_context
from trading_os.domain.market.calendar import CalendarSnapshot
from trading_os.domain.market.models import Candle, Tick
from trading_os.domain.primitives import Timeframe
from trading_os.infrastructure.mt5.protocol import WorkerError
from trading_os.shared.errors import Conflict, NotFound, Unavailable

router = APIRouter(prefix="/api/market", tags=["market"])

Symbol = Annotated[str, Path(pattern=r"^[A-Za-z0-9._#+\-]{1,32}$", description="The broker's own name, e.g. EURUSDm.")]


@router.get("/calendar", response_model=CalendarSnapshot, summary="The upcoming releases the news gate reads")
async def calendar(c: Core) -> CalendarSnapshot:
    return c.news.snapshot()


@router.get("/quotes", response_model=list[Tick], summary="The last quote of every watched symbol")
async def quotes(c: Core, account_id: AccountQuery = None) -> list[Tick]:
    account_id = await resolve_account(c, account_id)
    return [tick for name in c.market.watchlist(account_id) if (tick := c.market.tick(account_id, name)) is not None]


@router.get("/{symbol}", response_model=MarketQuote, summary="One symbol: last quote and broker specification")
async def quote(symbol: Symbol, c: Core, account_id: AccountQuery = None) -> MarketQuote:
    account_id = await resolve_account(c, account_id)
    spec = await c.market.require_spec(account_id, symbol)
    tick = c.market.tick(account_id, symbol)
    if spec is None and tick is None:
        raise NotFound(f"symbol {symbol!r} is unknown on this account's terminal", code="symbol_not_found")
    return MarketQuote(symbol=symbol, tick=tick, spec=spec)


@router.get(
    "/{symbol}/candles",
    response_model=list[Candle],
    summary="The last candles, oldest first; the newest may be forming",
)
async def candles(
    symbol: Symbol,
    c: Core,
    account_id: AccountQuery = None,
    timeframe: Timeframe = Timeframe.M5,
    count: Annotated[int, Query(ge=1, le=5000)] = 300,
) -> list[Candle]:
    account_id = await resolve_account(c, account_id)
    if not c.accounts.is_connected(account_id):
        raise Conflict("connect the account to read its candles", code="account_not_connected")
    try:
        return await c.market.recent_candles(account_id, symbol, timeframe, count)
    except WorkerError as error:
        raise Unavailable(
            "the terminal could not be read", code="mt5_unreadable", details={"workerCode": error.code}
        ) from error


@router.get(
    "/{symbol}/context", response_model=MarketContextState,
    summary="The ICT/SMC context at the last closed candle: bias, structure, liquidity, imbalances, confluence score",
)  # fmt: skip
async def context(
    symbol: Symbol,
    c: Core,
    account_id: AccountQuery = None,
    timeframe: Timeframe = Timeframe.M15,
    count: Annotated[int, Query(ge=20, le=2000)] = 300,
) -> MarketContextState:
    """Context, not a signal (ADR 0001/0002). The engine's thresholds are its defaults — scaled for gold; on a five-digit pair they
    are not meaningful until they are derived from the symbol (a known limit of the original, kept as it was)."""
    account_id = await resolve_account(c, account_id)
    if not c.accounts.is_connected(account_id):
        raise Conflict("connect the account to analyse its candles", code="account_not_connected")
    try:
        candles = await c.market.recent_candles(account_id, symbol, timeframe, count)
    except WorkerError as error:
        raise Unavailable(
            "the terminal could not be read", code="mt5_unreadable", details={"workerCode": error.code}
        ) from error
    return analyze_market_context(symbol, timeframe, [candle for candle in candles if candle.closed])
