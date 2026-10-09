"""S01 step 4 — the sweep on M5/M1: price exceeds a resting-liquidity level and reclaims it in the SAME candle (port of
``lib/setup/sweep.ts``): ``Low[0] < level and Close[0] > level`` for a buy, the mirror for a sell.

The first candle that touches the level decides the outcome: reclaimed in that bar is a sweep; broken without reclaiming is a
« cassure » and the search stops there — S01 is explicit that a cassure abandons the setup rather than leaving it pending for a later
bar. That is why the loop returns as soon as a candle touches the level.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from trading_os.domain.market.analysis.models import LiquidityKind
from trading_os.domain.market.models import Candle
from trading_os.domain.primitives import DomainModel, Side


class SweepLevel(DomainModel):
    kind: LiquidityKind
    price: float


class SweepEvent(DomainModel):
    level: SweepLevel
    side: Side
    swept_at: datetime
    wick_extreme: float  # the wick extreme of the sweeping candle — the anchor of the stop (step 7)


def detect_sweep(candles: Sequence[Candle], level: SweepLevel, side: Side) -> SweepEvent | None:
    for c in candles:
        touched = c.low < level.price if side is Side.BUY else c.high > level.price
        if not touched:
            continue
        reclaimed = c.close > level.price if side is Side.BUY else c.close < level.price
        if reclaimed:
            return SweepEvent(
                level=level, side=side, swept_at=c.open_time, wick_extreme=c.low if side is Side.BUY else c.high
            )
        return None  # touched the level but closed beyond it -> cassure, not a sweep
    return None  # level never touched in this window
