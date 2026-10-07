"""Journal facts. A trade is reconstructed from what was recorded at the real events, never recomputed later:
the capture rows are immutable (T05) and carry the window of candles the cockpit may draw — a boundary that is stored
and can never be widened, a stronger non-anticipation guarantee than a static image."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from trading_os.domain.primitives import AccountId, DomainModel, Side, SymbolCode


class TradeCapture(DomainModel):
    account_id: AccountId
    broker_position_id: str
    kind: Literal["entry", "exit"]
    symbol: SymbolCode
    timeframe: str
    window_start_utc: datetime
    window_end_utc: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    exit_price: float | None = None  # None on the entry row
    captured_at: datetime


class JournalTrade(DomainModel):
    broker_position_id: str
    symbol: SymbolCode
    side: Side
    volume: float
    entry_price: float | None
    exit_price: float
    realized_pnl: float
    stop_loss: float | None
    opened_at: datetime | None
    closed_at: datetime
    has_capture: bool
