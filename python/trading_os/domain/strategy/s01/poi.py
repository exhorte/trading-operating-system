"""S01 step 6 — the point of interest: the FVG left by the displacement, falling back to the order block at the origin of the move when
the FVG is already mitigated; CE (consequent encroachment) is the zone's midpoint (port of ``lib/setup/poi.ts``).

The Breaker Block fallback (also named in S01) is out of v1 scope: no detector for it exists, and adding one is new strategy geometry,
not assembly. A proposal with no usable FVG or order block simply fails (returns ``None``) instead of forcing a Breaker that does not
exist.

S01's invalidation rule (« clôture de corps au-delà du CE ») is a stricter, earlier signal than the analysis engine's own
``mitigated_at`` (a 100 %-fill measure) — ``is_invalidated_by_ce`` is new logic, not a duplicate.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from trading_os.domain.market.analysis.models import OrderBlock
from trading_os.domain.market.models import Candle
from trading_os.domain.primitives import Bias, DomainModel, Side
from trading_os.domain.strategy.s01.displacement import DisplacementEvent


class PointOfInterest(DomainModel):
    kind: Literal["fvg", "order_block"]
    high: float
    low: float
    ce: float
    formed_at: datetime


def _side_to_bias(side: Side) -> Bias:
    return Bias.BULLISH if side is Side.BUY else Bias.BEARISH


def point_of_interest_for(
    displacement: DisplacementEvent, order_blocks: Sequence[OrderBlock], side: Side
) -> PointOfInterest | None:
    gap = displacement.fair_value_gap
    if gap.mitigated_at is None:
        return PointOfInterest(
            kind="fvg", high=gap.high, low=gap.low, ce=(gap.high + gap.low) / 2, formed_at=gap.detected_at
        )

    candidates = [
        ob
        for ob in order_blocks
        if ob.direction is _side_to_bias(side) and ob.detected_at < displacement.occurred_at and ob.mitigated_at is None
    ]
    if not candidates:
        return None  # FVG already filled, no usable order block either -> no valid POI
    fallback = candidates[-1]
    return PointOfInterest(
        kind="order_block", high=fallback.high, low=fallback.low, ce=(fallback.high + fallback.low) / 2,
        formed_at=fallback.detected_at,
    )  # fmt: skip


def is_invalidated_by_ce(poi: PointOfInterest, side: Side, candles_after_formation: Sequence[Candle]) -> bool:
    """True once a candle BODY (not a wick) closes beyond the POI's CE — S01's invalidation rule. It only decides whether the
    setup is invalidated; what to do about a pending order versus an open position is the caller's concern."""
    return any((c.close < poi.ce) if side is Side.BUY else (c.close > poi.ce) for c in candles_after_formation)
