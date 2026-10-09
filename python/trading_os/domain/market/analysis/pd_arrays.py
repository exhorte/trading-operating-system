"""PD-array (Premium/Discount array) detection: fair value gaps and order blocks (port of ``lib/analysis/pd-arrays.ts``).

Both are detected from strictly past candles at their formation bar; the mitigation scan that follows uses only later candles, so a
gap/block is never labelled with information from before it existed (no look-ahead).
"""

from __future__ import annotations

from collections.abc import Sequence

from trading_os.domain.market.analysis.models import FairValueGap, OrderBlock, StructureShift
from trading_os.domain.market.models import Candle
from trading_os.domain.primitives import Bias, SymbolCode, Timeframe
from trading_os.shared.numbers import js_round


def _clamp_percent(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 100:
        return 100.0
    return js_round(value * 10) / 10


def detect_fair_value_gaps(candles: Sequence[Candle], min_size: float) -> list[FairValueGap]:
    """Three-candle imbalance: a bullish FVG is a gap between ``candle[i-2].high`` and ``candle[i].low``; a bearish FVG is the
    mirror. Fill and mitigation are measured from the candles that follow formation."""
    gaps: list[FairValueGap] = []
    if len(candles) < 3:
        return gaps
    symbol, timeframe = candles[0].symbol, candles[0].timeframe

    for i in range(2, len(candles)):
        left = candles[i - 2]
        right = candles[i]

        # Bullish gap: prior high below current low.
        if right.low - left.high >= min_size:
            gaps.append(_finalize_gap(candles, i, symbol, timeframe, Bias.BULLISH, high=right.low, low=left.high))
            continue
        # Bearish gap: prior low above current high.
        if left.low - right.high >= min_size:
            gaps.append(_finalize_gap(candles, i, symbol, timeframe, Bias.BEARISH, high=left.low, low=right.high))

    return gaps


def _finalize_gap(
    candles: Sequence[Candle], formed_at: int, symbol: SymbolCode, timeframe: Timeframe, direction: Bias,
    *, high: float, low: float,
) -> FairValueGap:  # fmt: skip
    span = high - low
    filled_percent = 0.0
    mitigated_at = None

    for t in range(formed_at + 1, len(candles)):
        c = candles[t]
        penetration = high - c.low if direction is Bias.BULLISH else c.high - low
        filled_percent = max(filled_percent, _clamp_percent((penetration / span) * 100))
        if filled_percent >= 100:
            mitigated_at = c.open_time
            break

    return FairValueGap(
        fvg_id=f"fvg-{formed_at}", symbol=symbol, timeframe=timeframe, direction=direction, high=high, low=low,
        filled_percent=filled_percent, mitigated_at=mitigated_at, detected_at=candles[formed_at].open_time,
    )  # fmt: skip


def detect_order_blocks(candles: Sequence[Candle], shifts: Sequence[StructureShift]) -> list[OrderBlock]:
    """The last opposing candle before a structure shift's displacement: a bullish shift is preceded by the last down-candle
    (bullish OB), a bearish shift by the last up-candle (bearish OB)."""
    blocks: list[OrderBlock] = []
    if len(candles) == 0:
        return blocks
    symbol, timeframe = candles[0].symbol, candles[0].timeframe
    index_by_time = {c.open_time: i for i, c in enumerate(candles)}

    for shift in shifts:
        shift_index = index_by_time.get(shift.occurred_at)
        if shift_index is None:
            continue
        wants_down_candle = shift.direction is Bias.BULLISH
        ob_index = -1
        for k in range(shift_index - 1, -1, -1):
            opposing = candles[k].close < candles[k].open if wants_down_candle else candles[k].close > candles[k].open
            if opposing:
                ob_index = k
                break
        if ob_index == -1:
            continue

        ob = candles[ob_index]
        mitigated_at = None
        for t in range(shift_index + 1, len(candles)):
            if candles[t].low <= ob.high and candles[t].high >= ob.low:
                mitigated_at = candles[t].open_time
                break

        blocks.append(
            OrderBlock(
                order_block_id=f"ob-{ob_index}", symbol=symbol, timeframe=timeframe, direction=shift.direction,
                high=ob.high, low=ob.low, mitigated_at=mitigated_at, detected_at=ob.open_time,
            )
        )  # fmt: skip

    return blocks
