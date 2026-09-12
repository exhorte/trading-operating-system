/**
 * S01 step 1 — daily bias from H4 and D1 structure.
 *
 * Pure assembly over lib/analysis/structure.ts: BOS/CHoCH is already
 * validated in body close and free of look-ahead there, so nothing new is
 * detected here — only combined. "Une seule direction autorisée pour la
 * journée" (S01) means H4 and D1 must agree; any disagreement, or either
 * timeframe having no confirmed shift yet, is treated the same as S01's own
 * "en consolidation, il n'y a pas de biais, donc pas de trade" — bias is
 * neutral and the pipeline stops here.
 */

import type { Candle } from "@/lib/domain/market";
import type { Bias } from "@/lib/domain/primitives";
import { detectStructureShifts, structuralBias } from "@/lib/analysis/structure";
import { detectSwings } from "@/lib/analysis/swings";

function timeframeBias(candles: Candle[], swingLookback: number): Bias {
  const swings = detectSwings(candles, swingLookback);
  const shifts = detectStructureShifts(candles, swings, swingLookback);
  return structuralBias(shifts);
}

/** H4 and D1 must agree on direction; anything else is "neutral" (no trade). */
export function dailyBias(h4Candles: Candle[], d1Candles: Candle[], swingLookback: number): Bias {
  const h4 = timeframeBias(h4Candles, swingLookback);
  const d1 = timeframeBias(d1Candles, swingLookback);
  return h4 === d1 && h4 !== "neutral" ? h4 : "neutral";
}
