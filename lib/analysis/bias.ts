/**
 * Directional bias and premium/discount location.
 *
 * MVP bias is the structural bias (last BOS/CHOCH direction). Premium/discount
 * describes where price sits inside the most recent swing range and feeds the
 * scoring stage, not the directional call itself.
 */

import type { Bias } from "@/lib/domain/primitives";
import type { PriceLocation, Swing } from "./types";

/** MVP: directional bias follows market structure. */
export function computeBias(structuralBias: Bias): Bias {
  return structuralBias;
}

/** Where `price` sits inside the highest-high / lowest-low swing range. */
export function priceLocationOf(price: number, swings: Swing[]): PriceLocation {
  const highs = swings.filter((s) => s.kind === "high").map((s) => s.price);
  const lows = swings.filter((s) => s.kind === "low").map((s) => s.price);
  if (highs.length === 0 || lows.length === 0) {
    return "equilibrium";
  }
  const hi = Math.max(...highs);
  const lo = Math.min(...lows);
  if (hi <= lo) {
    return "equilibrium";
  }
  const ratio = (price - lo) / (hi - lo);
  if (ratio > 0.55) return "premium";
  if (ratio < 0.45) return "discount";
  return "equilibrium";
}
