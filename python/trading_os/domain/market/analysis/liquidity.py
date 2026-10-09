"""Liquidity detection: equal highs/lows (relative-equal within a tolerance), previous-day high/low, and their swept state (port of
``lib/analysis/liquidity.ts``).

A level is « swept » once a later candle's wick trades beyond it — the classic draw-on-liquidity event. The sweep scan only looks
forward from the bar that established the level (no look-ahead).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from trading_os.domain.market.analysis.models import LiquidityKind, LiquidityLevel, Swing
from trading_os.domain.market.models import Candle
from trading_os.shared.numbers import js_round


@dataclass
class _Cluster:
    price: float
    formed_at: int
    formed_time: datetime
    members: int


def _cluster_swings(swings: Sequence[Swing], tolerance: float) -> list[_Cluster]:
    clusters: list[_Cluster] = []
    for swing in swings:
        hit = next((c for c in clusters if abs(c.price - swing.price) <= tolerance), None)
        if hit is not None:
            hit.price = (hit.price * hit.members + swing.price) / (hit.members + 1)
            hit.members += 1
            if swing.index > hit.formed_at:
                hit.formed_at = swing.index
                hit.formed_time = swing.time
        else:
            clusters.append(_Cluster(price=swing.price, formed_at=swing.index, formed_time=swing.time, members=1))
    return clusters


def first_sweep(
    candles: Sequence[Candle], from_index: int, price: float, side: Literal["above", "below"]
) -> datetime | None:
    """The open time of the first candle after ``from_index`` whose wick trades beyond ``price``."""
    for t in range(from_index + 1, len(candles)):
        if side == "above" and candles[t].high > price:
            return candles[t].open_time
        if side == "below" and candles[t].low < price:
            return candles[t].open_time
    return None


def _day_key(candle: Candle) -> date:
    return candle.open_time.astimezone(UTC).date()


def detect_liquidity(candles: Sequence[Candle], swings: Sequence[Swing], tolerance: float) -> list[LiquidityLevel]:
    levels: list[LiquidityLevel] = []
    if len(candles) == 0:
        return levels
    symbol, timeframe = candles[0].symbol, candles[0].timeframe

    def push_level(
        kind: LiquidityKind, price: float, formed_at: int, detected_at: datetime, side: Literal["above", "below"]
    ) -> None:
        levels.append(
            LiquidityLevel(
                level_id=f"liq-{kind.value}-{formed_at}", symbol=symbol, timeframe=timeframe, kind=kind,
                price=js_round(price * 100) / 100, swept_at=first_sweep(candles, formed_at, price, side),
                detected_at=detected_at,
            )
        )  # fmt: skip

    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]

    for cluster in _cluster_swings(highs, tolerance):
        if cluster.members >= 2:
            push_level(LiquidityKind.EQUAL_HIGHS, cluster.price, cluster.formed_at, cluster.formed_time, "above")
    for cluster in _cluster_swings(lows, tolerance):
        if cluster.members >= 2:
            push_level(LiquidityKind.EQUAL_LOWS, cluster.price, cluster.formed_at, cluster.formed_time, "below")

    # Previous-day high/low become today's draw-on-liquidity targets.
    last_day = _day_key(candles[-1])
    previous_days = [c for c in candles if _day_key(c) < last_day]
    if previous_days:
        previous_day = _day_key(previous_days[-1])
        prior = [c for c in previous_days if _day_key(c) == previous_day]
        pdh = max(c.high for c in prior)
        pdl = min(c.low for c in prior)
        today_start = next(i for i, c in enumerate(candles) if _day_key(c) == last_day)
        detected_at = candles[today_start].open_time
        push_level(LiquidityKind.PREVIOUS_DAY_HIGH, pdh, today_start, detected_at, "above")
        push_level(LiquidityKind.PREVIOUS_DAY_LOW, pdl, today_start, detected_at, "below")

    return levels
