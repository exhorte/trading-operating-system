"""S01 step 2 — the dealing range on 1H: the last impulsive leg between two alternating swings, its external high/low, and a strict
50 % equilibrium (port of ``lib/setup/dealing-range.ts``).

Deliberately NOT the analysis engine's ``price_location_of``: that one bands premium/discount with a 45-55 % neutral zone (a scoring
heuristic). S01 asks for a strict half-split — « achat uniquement SOUS l'équilibre, vente uniquement AU-DESSUS » — with no neutral band.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from trading_os.domain.market.analysis.swings import detect_swings
from trading_os.domain.market.models import Candle
from trading_os.domain.primitives import DomainModel

RangeLocation = Literal["premium", "discount", "equilibrium"]


class DealingRange(DomainModel):
    external_high: float
    external_low: float
    equilibrium: float


def last_dealing_range(candles: Sequence[Candle], swing_lookback: int) -> DealingRange | None:
    """The most recent impulsive leg: the last confirmed swing and the nearest earlier swing of the opposite kind. ``None`` when
    fewer than two swings are known yet (nothing to anchor a range on)."""
    swings = sorted(detect_swings(candles, swing_lookback), key=lambda swing: swing.index)
    if len(swings) < 2:
        return None

    last = swings[-1]
    for i in range(len(swings) - 2, -1, -1):
        if swings[i].kind != last.kind:
            external_high = last.price if last.kind == "high" else swings[i].price
            external_low = last.price if last.kind == "low" else swings[i].price
            return DealingRange(
                external_high=external_high, external_low=external_low, equilibrium=(external_high + external_low) / 2
            )
    return None


def location_in_range(price: float, dealing_range: DealingRange) -> RangeLocation:
    """Strict half-split location of ``price`` inside the range. No neutral band."""
    if dealing_range.external_high <= dealing_range.external_low:
        return "equilibrium"
    if price < dealing_range.equilibrium:
        return "discount"
    if price > dealing_range.equilibrium:
        return "premium"
    return "equilibrium"
