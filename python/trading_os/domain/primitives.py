"""Vocabulary shared by every domain model.

Casing is a contract: ``Side`` values are lowercase because the database rows (``closed_trades.side``) and the
cockpit already use ``buy``/``sell``; the MT5 edge speaks ``BUY``/``SELL`` and is converted once, in
``infrastructure/mt5/wire.py``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

AccountId = str
SymbolCode = str


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"

    @property
    def direction(self) -> int:
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY


class Timeframe(StrEnum):
    M1 = "M1"
    M3 = "M3"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"

    @property
    def minutes(self) -> int:
        return _TIMEFRAME_MINUTES[self]


_TIMEFRAME_MINUTES = {
    Timeframe.M1: 1,
    Timeframe.M3: 3,
    Timeframe.M5: 5,
    Timeframe.M15: 15,
    Timeframe.M30: 30,
    Timeframe.H1: 60,
    Timeframe.H4: 240,
    Timeframe.D1: 1440,
    Timeframe.W1: 10080,
}


class TradingSession(StrEnum):
    """ICT-style session buckets used for context tagging and attribution."""

    ASIA = "asia"
    LONDON = "london"
    NEW_YORK_AM = "new_york_am"
    NEW_YORK_PM = "new_york_pm"
    OFF_SESSION = "off_session"


class Bias(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class DomainModel(BaseModel):
    """Base of every domain model: immutable, camelCase on the wire, built from either spelling."""

    model_config = ConfigDict(frozen=True, populate_by_name=True, alias_generator=to_camel)
