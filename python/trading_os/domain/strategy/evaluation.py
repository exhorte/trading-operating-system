"""One evaluation of a strategy against one instrument — whether or not it produced a proposal.

This is the instrument of measurement (ADR 0011), never a performance metric. ``event_at`` is deliberately dual-purpose:

* ``proposed`` — the displacement candle's open time. A rolling evaluation re-detects the same real setup on several
  consecutive candles; keying on the displacement's own, stable timestamp makes re-detection an idempotent upsert of the
  same row instead of a stream of duplicates for one real event.
* ``blocked`` — the open time of the candle the evaluation ran against: one row per evaluated candle is exactly what is
  wanted, since the distribution of block reasons across a session *is* the measurement.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from trading_os.domain.primitives import DomainModel, Side, SymbolCode


class StrategyEvaluation(DomainModel):
    symbol: SymbolCode
    event_at: datetime
    status: Literal["proposed", "blocked"]
    stage: str | None = None  # blocked: where the sequence stopped
    detail: str | None = None
    side: Side | None = None  # proposed only
    swept_level_kind: str | None = None
    swept_level_price: float | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    cost_ratio: float | None = None
    risk_reward_ratio: float | None = None
