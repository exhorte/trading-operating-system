/**
 * S01 step 7 — stop loss: beyond the sweep's wick extreme plus a spread
 * buffer. If the resulting distance exceeds the symbol's calibrated
 * ceiling, the setup is refused — but that ceiling isn't a fixed number
 * anywhere in S01 ("plafond calibré du symbole", to come from the account
 * profile in EA-04), so `maxDistance` is optional: omitted, no ceiling is
 * applied yet, matching how the cost gate's own threshold is a parameter
 * with a provisional default rather than a hardcoded constant.
 */

import type { Side } from "@/lib/domain/primitives";

export interface StopLossResult {
  price: number;
  distance: number;
}

export function computeStopLoss(
  side: Side,
  sweepWickExtreme: number,
  spreadBuffer: number,
  entryPrice: number,
  maxDistance?: number,
): StopLossResult | null {
  const price = side === "buy" ? sweepWickExtreme - spreadBuffer : sweepWickExtreme + spreadBuffer;
  const distance = Math.abs(entryPrice - price);
  if (maxDistance !== undefined && distance > maxDistance) {
    return null; // stop too wide for this symbol's calibrated ceiling
  }
  return { price, distance };
}
