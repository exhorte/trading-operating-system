"""Market-structure detection: BOS (break of structure) and CHOCH (change of character) (port of ``lib/analysis/structure.ts``).

A close beyond the most recent known swing is a BOS when it extends the prevailing bias, or a CHOCH when it breaks against it (the
first sign of a reversal). Swings are only « known » ``lookback`` candles after they form, so a candle can never break a pivot the
market had not yet confirmed (no look-ahead).
"""

from __future__ import annotations

from collections.abc import Sequence

from trading_os.domain.market.analysis.models import StructureShift, StructureShiftKind, Swing
from trading_os.domain.market.models import Candle
from trading_os.domain.primitives import Bias


def detect_structure_shifts(candles: Sequence[Candle], swings: Sequence[Swing], lookback: int) -> list[StructureShift]:
    shifts: list[StructureShift] = []
    if len(candles) == 0:
        return shifts

    symbol, timeframe = candles[0].symbol, candles[0].timeframe
    ordered = sorted(swings, key=lambda swing: swing.index)

    cursor = 0
    last_high: Swing | None = None
    last_low: Swing | None = None
    broken_high_index = -1
    broken_low_index = -1
    bias = Bias.NEUTRAL

    for t in range(len(candles)):
        # Promote every swing confirmed by time t into the « known » reference set.
        while cursor < len(ordered) and ordered[cursor].index + lookback <= t:
            swing = ordered[cursor]
            if swing.kind == "high":
                last_high = swing
            else:
                last_low = swing
            cursor += 1

        close = candles[t].close

        if last_high is not None and last_high.index != broken_high_index and close > last_high.price:
            kind = (
                StructureShiftKind.CHANGE_OF_CHARACTER
                if bias is Bias.BEARISH
                else StructureShiftKind.BREAK_OF_STRUCTURE
            )
            shifts.append(
                StructureShift(
                    shift_id=f"shift-{t}", symbol=symbol, timeframe=timeframe, kind=kind, direction=Bias.BULLISH,
                    broken_level=last_high.price, occurred_at=candles[t].open_time,
                )
            )  # fmt: skip
            broken_high_index = last_high.index
            bias = Bias.BULLISH
        elif last_low is not None and last_low.index != broken_low_index and close < last_low.price:
            kind = (
                StructureShiftKind.CHANGE_OF_CHARACTER
                if bias is Bias.BULLISH
                else StructureShiftKind.BREAK_OF_STRUCTURE
            )
            shifts.append(
                StructureShift(
                    shift_id=f"shift-{t}", symbol=symbol, timeframe=timeframe, kind=kind, direction=Bias.BEARISH,
                    broken_level=last_low.price, occurred_at=candles[t].open_time,
                )
            )  # fmt: skip
            broken_low_index = last_low.index
            bias = Bias.BEARISH

    return shifts


def structural_bias(shifts: Sequence[StructureShift]) -> Bias:
    """Structural bias implied by the most recent shift, neutral if none."""
    return shifts[-1].direction if shifts else Bias.NEUTRAL
