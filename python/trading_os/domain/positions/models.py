"""Open exposure and pending orders, as the broker reports them."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from trading_os.domain.primitives import AccountId, DomainModel, Side, SymbolCode


class Position(DomainModel):
    """One open position. ``position_id`` is MT5's POSITION_IDENTIFIER (stable for the life of the position),
    **never** the ticket — the two diverge on broker service operations (incident of 2026-09-05)."""

    position_id: str
    account_id: AccountId
    symbol: SymbolCode
    side: Side
    volume: float = Field(gt=0)
    entry_price: float
    current_price: float | None = None
    stop_loss: float = 0.0  # 0.0 = no stop (MT5's own convention)
    take_profit: float = 0.0
    unrealized_pnl: float = 0.0
    r_multiple: float = 0.0
    magic_number: int | None = None
    comment: str = ""
    strategy_id: str = "manual"
    opened_at: datetime | None = None

    @property
    def has_stop(self) -> bool:
        return self.stop_loss > 0


class PendingOrder(DomainModel):
    order_id: str
    account_id: AccountId
    symbol: SymbolCode
    side: Side
    order_type: str  # limit | stop | stop_limit …
    volume: float
    price: float
    stop_loss: float = 0.0
    take_profit: float = 0.0
    magic_number: int | None = None
    comment: str = ""
    placed_at: datetime | None = None


class ClosedTrade(DomainModel):
    """A fully closed position with its net result (every deal summed: profit + commission + swap)."""

    account_id: AccountId
    broker_position_id: str
    symbol: SymbolCode
    side: Side
    volume: float
    realized_pnl: float
    exit_price: float
    closed_at: datetime
