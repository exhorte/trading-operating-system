/**
 * S01 step 6 — point of interest: the FVG left by the displacement, falling
 * back to the order block at the origin of the move when the FVG is
 * already mitigated. CE (consequent encroachment) is the zone's midpoint.
 *
 * Breaker Block fallback (also named in S01) is out of v1 scope: no
 * detector for it exists anywhere in lib/analysis/, and adding one is new
 * strategy geometry, not assembly — flagged in the EA-01 fiche rather than
 * built silently here. A proposal with no usable FVG or order block simply
 * fails (returns null) instead of forcing a Breaker that doesn't exist.
 *
 * S01's invalidation rule ("clôture de corps au-delà du CE") is a stricter,
 * earlier signal than lib/analysis/pd-arrays.ts's own `mitigatedAt` (a
 * 100%-fill measure) — isInvalidatedByCe is new logic, not a duplicate.
 */

import type { Candle } from "@/lib/domain/market";
import type { OrderBlock } from "@/lib/domain/analysis";
import type { DisplacementEvent } from "./displacement";
import type { Bias, Side, UtcTimestamp } from "@/lib/domain/primitives";

export interface PointOfInterest {
  kind: "fvg" | "order_block";
  high: number;
  low: number;
  ce: number;
  formedAt: UtcTimestamp;
}

function sideToBias(side: Side): Bias {
  return side === "buy" ? "bullish" : "bearish";
}

export function pointOfInterestFor(
  displacement: DisplacementEvent,
  orderBlocks: OrderBlock[],
  side: Side,
): PointOfInterest | null {
  const gap = displacement.fairValueGap;
  if (gap.mitigatedAt === null) {
    return { kind: "fvg", high: gap.high, low: gap.low, ce: (gap.high + gap.low) / 2, formedAt: gap.detectedAt };
  }

  const fallback = orderBlocks
    .filter(
      (ob) =>
        ob.direction === sideToBias(side) && ob.detectedAt < displacement.occurredAt && ob.mitigatedAt === null,
    )
    .at(-1);
  if (!fallback) {
    return null; // FVG already filled, no usable order block either -> no valid POI
  }
  return {
    kind: "order_block",
    high: fallback.high,
    low: fallback.low,
    ce: (fallback.high + fallback.low) / 2,
    formedAt: fallback.detectedAt,
  };
}

/** True once a candle body (not a wick) closes beyond the POI's CE — S01's
 * invalidation rule: "ordre annulé s'il n'est pas déclenché, position
 * coupée s'il l'est." Only decides whether it's invalidated; what to do
 * about a pending order vs. an open position is the caller's concern. */
export function isInvalidatedByCe(poi: PointOfInterest, side: Side, candlesAfterFormation: Candle[]): boolean {
  return candlesAfterFormation.some((c) => (side === "buy" ? c.close < poi.ce : c.close > poi.ce));
}
