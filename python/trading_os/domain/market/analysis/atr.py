"""Average True Range (Wilder) (port of ``lib/analysis/atr.ts``). Pure.

A volatility unit for stop-buffer sizing instead of a fixed price offset. It reads only the candles it is given (the caller passes a
slice up to the evaluation bar), so the value at bar ``i`` never depends on a future bar.

The totals are added in a loop, in order, on purpose: ``sum()`` compensates float additions from Python 3.12 and would not give the
bit-identical result the golden vectors were generated with.
"""

from __future__ import annotations

from collections.abc import Sequence

from trading_os.domain.market.models import Candle


def _true_range(candle: Candle, prev_close: float) -> float:
    return max(candle.high - candle.low, abs(candle.high - prev_close), abs(candle.low - prev_close))


def average_true_range(candles: Sequence[Candle], period: int) -> float:
    """Wilder ATR at the last candle, over ``period``: seeded with the simple mean of the first ``period`` true ranges, then
    smoothed. 0 when there are too few candles to form a single true range (< 2)."""
    if period < 1 or len(candles) < 2:
        return 0.0

    true_ranges = [_true_range(candles[i], candles[i - 1].close) for i in range(1, len(candles))]

    # Fewer than ``period`` true ranges: their simple mean, so a short window still gets a sane volatility estimate.
    if len(true_ranges) <= period:
        total = 0.0
        for tr in true_ranges:
            total += tr
        return total / len(true_ranges)

    seed = 0.0
    for tr in true_ranges[:period]:
        seed += tr
    atr = seed / period
    for i in range(period, len(true_ranges)):
        atr = (atr * (period - 1) + true_ranges[i]) / period
    return atr
