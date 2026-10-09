"""Directional bias and premium/discount location (port of ``lib/analysis/bias.ts``).

The MVP bias is the structural bias (the last BOS/CHOCH direction). Premium/discount describes where price sits inside the most
recent swing range and feeds the scoring stage, not the directional call itself.
"""

from __future__ import annotations

from collections.abc import Sequence

from trading_os.domain.market.analysis.models import PriceLocation, Swing
from trading_os.domain.primitives import Bias


def compute_bias(structural: Bias) -> Bias:
    """MVP: the directional bias follows market structure."""
    return structural


def price_location_of(price: float, swings: Sequence[Swing]) -> PriceLocation:
    """Where ``price`` sits inside the highest-high / lowest-low swing range (a 45-55 % neutral band — a scoring heuristic)."""
    highs = [s.price for s in swings if s.kind == "high"]
    lows = [s.price for s in swings if s.kind == "low"]
    if not highs or not lows:
        return "equilibrium"
    hi = max(highs)
    lo = min(lows)
    if hi <= lo:
        return "equilibrium"
    ratio = (price - lo) / (hi - lo)
    if ratio > 0.55:
        return "premium"
    if ratio < 0.45:
        return "discount"
    return "equilibrium"
