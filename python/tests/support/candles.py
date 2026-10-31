"""Deterministic candle builders (port of ``lib/analysis/test-helpers.ts``): times increase by one step from a fixed Monday so
fixtures are stable and ordered, and a bar is described by its high and low (open and close default to the midpoint)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import TypedDict

from trading_os.domain.market.models import Candle
from trading_os.domain.primitives import SymbolCode, Timeframe

BASE_EPOCH = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)  # Monday 2026-01-05 00:00 UTC


class Bar(TypedDict, total=False):
    high: float
    low: float
    open: float
    close: float


def candle_at(
    index: int,
    high: float,
    low: float,
    *,
    open: float | None = None,
    close: float | None = None,
    volume: float = 100.0,
    symbol: SymbolCode = "XAUUSD",
    timeframe: Timeframe = Timeframe.M15,
    step_minutes: int = 15,
    closed: bool = True,
) -> Candle:
    middle = (high + low) / 2
    return Candle(
        symbol=symbol, timeframe=timeframe, open_time=BASE_EPOCH + timedelta(minutes=index * step_minutes),
        open=middle if open is None else open, high=high, low=low, close=middle if close is None else close,
        volume=volume, closed=closed,
    )  # fmt: skip


def series(
    bars: Sequence[tuple[float, float] | Bar],
    *,
    symbol: SymbolCode = "XAUUSD",
    timeframe: Timeframe = Timeframe.M15,
    step_minutes: int = 15,
) -> list[Candle]:
    """A series from ``(high, low)`` pairs or ``{"high", "low", "open", "close"}`` dicts, auto-indexed."""
    out: list[Candle] = []
    for index, bar in enumerate(bars):
        if isinstance(bar, tuple):
            out.append(candle_at(index, bar[0], bar[1], symbol=symbol, timeframe=timeframe, step_minutes=step_minutes))
        else:
            out.append(
                candle_at(
                    index, bar["high"], bar["low"], open=bar.get("open"), close=bar.get("close"), symbol=symbol,
                    timeframe=timeframe, step_minutes=step_minutes,
                )
            )  # fmt: skip
    return out
