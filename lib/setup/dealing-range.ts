/**
 * S01 step 2 — dealing range on 1H: the last impulsive leg between two
 * alternating swings, its external high/low, and a strict 50% equilibrium.
 *
 * Deliberately NOT lib/analysis/bias.ts's priceLocationOf: that function
 * bands premium/discount with a 45-55% neutral zone (a scoring heuristic).
 * S01 asks for a strict half-split ("achat uniquement SOUS l'équilibre,
 * vente uniquement AU-DESSUS") with no neutral band, so this is new,
 * narrower logic over the range this function isolates — not a rewrite of
 * an existing detector.
 */

import type { Candle } from "@/lib/domain/market";
import { detectSwings } from "@/lib/analysis/swings";

export interface DealingRange {
  externalHigh: number;
  externalLow: number;
  equilibrium: number;
}

export type RangeLocation = "premium" | "discount" | "equilibrium";

/**
 * The most recent impulsive leg: the last confirmed swing and the nearest
 * earlier swing of the opposite kind. Null when fewer than two swings are
 * known yet (nothing to anchor a range on).
 */
export function lastDealingRange(candles: Candle[], swingLookback: number): DealingRange | null {
  const swings = [...detectSwings(candles, swingLookback)].sort((a, b) => a.index - b.index);
  if (swings.length < 2) {
    return null;
  }

  const last = swings[swings.length - 1];
  for (let i = swings.length - 2; i >= 0; i -= 1) {
    if (swings[i].kind !== last.kind) {
      const externalHigh = last.kind === "high" ? last.price : swings[i].price;
      const externalLow = last.kind === "low" ? last.price : swings[i].price;
      return { externalHigh, externalLow, equilibrium: (externalHigh + externalLow) / 2 };
    }
  }
  return null;
}

/** Strict half-split location of `price` inside `range`. No neutral band. */
export function locationInRange(price: number, range: DealingRange): RangeLocation {
  if (range.externalHigh <= range.externalLow) {
    return "equilibrium";
  }
  if (price < range.equilibrium) return "discount";
  if (price > range.equilibrium) return "premium";
  return "equilibrium";
}
