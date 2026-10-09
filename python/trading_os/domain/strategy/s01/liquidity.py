"""S01 step 3 — the liquidity map: PDH/PDL and equal highs/lows from the analysis engine, plus the Asia session high/low (not detected
there), and the choice of the trade's target and of the level a sweep is expected to trigger against (port of ``lib/setup/liquidity.ts``).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from trading_os.domain.market.analysis.liquidity import detect_liquidity, first_sweep
from trading_os.domain.market.analysis.models import LiquidityKind, LiquidityLevel, Swing
from trading_os.domain.market.models import Candle
from trading_os.domain.market.sessions import SessionWindow, session_for_timestamp
from trading_os.domain.primitives import Side, TradingSession

HIGH_SIDE_KINDS = (
    LiquidityKind.PREVIOUS_DAY_HIGH, LiquidityKind.SESSION_HIGH, LiquidityKind.EQUAL_HIGHS, LiquidityKind.BUY_SIDE,
)  # fmt: skip
LOW_SIDE_KINDS = (
    LiquidityKind.PREVIOUS_DAY_LOW, LiquidityKind.SESSION_LOW, LiquidityKind.EQUAL_LOWS, LiquidityKind.SELL_SIDE,
)  # fmt: skip


def _asia_levels(candles: Sequence[Candle], session_windows: Sequence[SessionWindow]) -> list[LiquidityLevel]:
    """High/low of the most recent contiguous Asia session found walking backward from the end of ``candles`` — not an all-time
    min/max across every Asia session in the series."""
    high = -math.inf
    low = math.inf
    last_asia_index = -1
    collecting = False

    for i in range(len(candles) - 1, -1, -1):
        is_asia = session_for_timestamp(candles[i].open_time, session_windows) is TradingSession.ASIA
        if is_asia:
            collecting = True
            high = max(high, candles[i].high)
            low = min(low, candles[i].low)
            if last_asia_index == -1:
                last_asia_index = i
        elif collecting:
            break  # walked out of the most recent Asia block
    if last_asia_index == -1:
        return []

    detected_at: datetime = candles[min(last_asia_index + 1, len(candles) - 1)].open_time
    symbol, timeframe = candles[0].symbol, candles[0].timeframe

    def level(kind: LiquidityKind, price: float, side: Literal["above", "below"]) -> LiquidityLevel:
        return LiquidityLevel(
            level_id=f"liq-{kind.value}-{last_asia_index}", symbol=symbol, timeframe=timeframe, kind=kind, price=price,
            swept_at=first_sweep(candles, last_asia_index, price, side), detected_at=detected_at,
        )  # fmt: skip

    return [level(LiquidityKind.SESSION_HIGH, high, "above"), level(LiquidityKind.SESSION_LOW, low, "below")]


def liquidity_pool(
    candles: Sequence[Candle],
    swings: Sequence[Swing],
    equal_level_tolerance: float,
    session_windows: Sequence[SessionWindow],
) -> list[LiquidityLevel]:
    """PDH/PDL and equal highs/lows (analysis engine) plus the Asia high/low, unified."""
    return [*detect_liquidity(candles, swings, equal_level_tolerance), *_asia_levels(candles, session_windows)]


def _nearest_unswept(
    pool: Sequence[LiquidityLevel], kinds: Sequence[LiquidityKind], from_price: float
) -> LiquidityLevel | None:
    candidates = [level for level in pool if level.kind in kinds and level.swept_at is None]
    if not candidates:
        return None
    best = candidates[0]
    for level in candidates[1:]:  # strictly nearer wins: on a tie the earlier level stays
        if abs(level.price - from_price) < abs(best.price - from_price):
            best = level
    return best


def opposing_target(pool: Sequence[LiquidityLevel], side: Side, from_price: float) -> LiquidityLevel | None:
    """The opposite, not-yet-purged pool the trade targets (S01: « la cible du trade est la poche opposée non encore purgée »).
    Convention: the nearest unswept candidate — a repo convention, adjustable after observation, not a rule stated numerically."""
    return _nearest_unswept(pool, HIGH_SIDE_KINDS if side is Side.BUY else LOW_SIDE_KINDS, from_price)


def sweep_trigger_candidate(pool: Sequence[LiquidityLevel], side: Side, from_price: float) -> LiquidityLevel | None:
    """The resting liquidity a sweep is expected to trigger against: the opposite side of ``opposing_target`` (a buy sweeps low-side
    liquidity, then targets high-side liquidity). Same nearest-candidate convention."""
    return _nearest_unswept(pool, LOW_SIDE_KINDS if side is Side.BUY else HIGH_SIDE_KINDS, from_price)
