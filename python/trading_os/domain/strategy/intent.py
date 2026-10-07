"""What a strategy asks for. A ``TradeIntent`` is *not* an order: it carries no volume (the Risk Engine sizes it)
and no authority — Strategy → Risk → Execution, never Strategy → Execution (ADR 0007)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from trading_os.domain.primitives import AccountId, DomainModel, Side, SymbolCode


class OrderKind(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class TradeIntent(DomainModel):
    intent_id: str
    account_id: AccountId
    strategy_id: str
    strategy_version: str
    symbol: SymbolCode  # broker-side name of the instrument on the account's terminal
    side: Side
    order_type: OrderKind = OrderKind.MARKET
    entry_price: float  # reference price: the live price for a market order, the planned level for a limit
    stop_loss: float
    take_profit: float
    created_at: datetime
    expires_at: datetime
    rationale: str = ""
    details: dict[str, float | str] = Field(default_factory=dict)
