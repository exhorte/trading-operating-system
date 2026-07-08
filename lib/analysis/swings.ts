/**
 * Swing (fractal pivot) detection.
 *
 * A swing high at index i requires candle[i].high to strictly exceed the highs
 * of `lookback` candles on BOTH sides; a swing low is the mirror on lows.
 * Confirmation needs `lookback` candles after the pivot, so the final
 * `lookback` candles never produce a swing — this is the no-look-ahead
 * guarantee: a pivot is only reported once the market has moved past it.
 */

import type { Candle } from "@/lib/domain/market";
import type { Swing } from "./types";

export function detectSwings(candles: Candle[], lookback: number): Swing[] {
  const swings: Swing[] = [];
  if (lookback < 1) {
    return swings;
  }

  for (let i = lookback; i < candles.length - lookback; i += 1) {
    const candle = candles[i];
    let isHigh = true;
    let isLow = true;

    for (let j = i - lookback; j <= i + lookback; j += 1) {
      if (j === i) {
        continue;
      }
      if (candles[j].high >= candle.high) {
        isHigh = false;
      }
      if (candles[j].low <= candle.low) {
        isLow = false;
      }
    }

    if (isHigh) {
      swings.push({ kind: "high", price: candle.high, index: i, time: candle.openTime });
    }
    // A single candle is not both a strict high and a strict low of its window.
    if (isLow) {
      swings.push({ kind: "low", price: candle.low, index: i, time: candle.openTime });
    }
  }

  return swings;
}
