/**
 * S01 step 4 — sweep on M5/M1: price exceeds a resting-liquidity level and
 * reclaims it in the SAME candle. `Low[0] < niveau ET Close[0] > niveau`
 * for a buy, the mirror for a sell.
 *
 * The first candle that touches the level decides the outcome: reclaimed in
 * that same bar is a sweep; broken without reclaiming is a "cassure" and
 * the search stops there — S01 is explicit that a cassure abandons the
 * setup rather than leaving it pending for a later bar. This is why the
 * loop returns as soon as a candle touches the level, rather than scanning
 * every candle for the first one that happens to reclaim.
 */

import type { Candle } from "@/lib/domain/market";
import type { LiquidityKind } from "@/lib/domain/analysis";
import type { Side } from "@/lib/domain/primitives";
import type { UtcTimestamp } from "@/lib/domain/primitives";

export interface SweepLevel {
  kind: LiquidityKind;
  price: number;
}

export interface SweepEvent {
  level: SweepLevel;
  side: Side;
  sweptAt: UtcTimestamp;
  /** The wick extreme of the sweeping candle — anchor for the stop (step 7). */
  wickExtreme: number;
}

export function detectSweep(candles: Candle[], level: SweepLevel, side: Side): SweepEvent | null {
  for (const c of candles) {
    const touched = side === "buy" ? c.low < level.price : c.high > level.price;
    if (!touched) {
      continue;
    }
    const reclaimed = side === "buy" ? c.close > level.price : c.close < level.price;
    if (reclaimed) {
      return { level, side, sweptAt: c.openTime, wickExtreme: side === "buy" ? c.low : c.high };
    }
    return null; // touched the level but closed beyond it -> cassure, not a sweep
  }
  return null; // level never touched in this window
}
