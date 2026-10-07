"""Market data models: symbol specifications, ticks, candles."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from trading_os.domain.primitives import DomainModel, SymbolCode, Timeframe


class SymbolSpec(DomainModel):
    """Everything needed to price and size an order on one broker symbol, as the broker reports it.

    ``tick_value`` and ``tick_value_loss`` are expressed in the **account currency** per ``tick_size`` move
    for 1.0 lot (MT5 converts at the current rate). A spec read from the broker — never a static table.
    """

    name: SymbolCode  # broker-side name, e.g. "EURUSDm"
    description: str = ""
    currency_base: str
    currency_profit: str
    currency_margin: str = ""
    digits: int = Field(ge=0)
    point: float = Field(gt=0)
    tick_size: float = Field(gt=0)
    tick_value: float = Field(ge=0)
    tick_value_loss: float | None = Field(default=None, ge=0)
    contract_size: float = Field(gt=0)
    volume_min: float = Field(gt=0)
    volume_max: float = Field(gt=0)
    volume_step: float = Field(gt=0)
    stops_level_points: int = Field(default=0, ge=0)
    freeze_level_points: int = Field(default=0, ge=0)
    trade_allowed: bool = True

    @property
    def loss_tick_value(self) -> float:
        """Value of one tick against a position (falls back to ``tick_value`` when the broker gives one number)."""
        return self.tick_value_loss if self.tick_value_loss else self.tick_value


class Tick(DomainModel):
    symbol: SymbolCode
    bid: float
    ask: float
    last: float | None = None
    time: datetime

    @property
    def spread(self) -> float:
        """Spread in price units."""
        return round(self.ask - self.bid, 10)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


class Candle(DomainModel):
    symbol: SymbolCode
    timeframe: Timeframe
    open_time: datetime  # bucket start, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    closed: bool = True
