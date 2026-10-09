"""Swing (fractal pivot) detection (port of ``lib/analysis/swings.ts``).

A swing high at index ``i`` requires ``candle[i].high`` to strictly exceed the highs of ``lookback`` candles on **both** sides; a
swing low is the mirror on lows. Confirmation needs ``lookback`` candles after the pivot, so the final ``lookback`` candles never
produce a swing — the no-look-ahead guarantee: a pivot is only reported once the market has moved past it.
"""

from __future__ import annotations

from collections.abc import Sequence

from trading_os.domain.market.analysis.models import Swing
from trading_os.domain.market.models import Candle


def detect_swings(candles: Sequence[Candle], lookback: int) -> list[Swing]:
    swings: list[Swing] = []
    if lookback < 1:
        return swings

    for i in range(lookback, len(candles) - lookback):
        candle = candles[i]
        is_high = True
        is_low = True

        for j in range(i - lookback, i + lookback + 1):
            if j == i:
                continue
            if candles[j].high >= candle.high:
                is_high = False
            if candles[j].low <= candle.low:
                is_low = False

        if is_high:
            swings.append(Swing(kind="high", price=candle.high, index=i, time=candle.open_time))
        # A single candle is not both a strict high and a strict low of its window.
        if is_low:
            swings.append(Swing(kind="low", price=candle.low, index=i, time=candle.open_time))

    return swings
