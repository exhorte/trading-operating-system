/**
 * Average True Range (Wilder). Pure; imports only lib/domain.
 *
 * A volatility unit for stop-buffer sizing instead of a fixed price offset.
 * Kept as a standalone helper — it does NOT touch MarketContextState or the
 * score, so the analysis engine and its no-look-ahead invariant are unchanged.
 *
 * Reads only candles up to the evaluation bar (the caller passes a slice), so
 * the value at bar i never depends on a future bar.
 */

import type { Candle } from "@/lib/domain/market";

/** True range of `candle` given the previous close. */
function trueRange(candle: Candle, prevClose: number): number {
  return Math.max(
    candle.high - candle.low,
    Math.abs(candle.high - prevClose),
    Math.abs(candle.low - prevClose),
  );
}

/**
 * Wilder ATR at the last candle of `candles`, over `period`. Seeded with the
 * simple mean of the first `period` true ranges, then smoothed. Returns 0 when
 * there are too few candles to form a single true range (< 2).
 */
export function averageTrueRange(candles: Candle[], period: number): number {
  if (period < 1 || candles.length < 2) {
    return 0;
  }

  const trs: number[] = [];
  for (let i = 1; i < candles.length; i += 1) {
    trs.push(trueRange(candles[i], candles[i - 1].close));
  }

  // Fewer than `period` true ranges: fall back to their simple mean so the
  // caller still gets a sane volatility estimate on short windows.
  if (trs.length <= period) {
    return trs.reduce((sum, tr) => sum + tr, 0) / trs.length;
  }

  let atr = trs.slice(0, period).reduce((sum, tr) => sum + tr, 0) / period;
  for (let i = period; i < trs.length; i += 1) {
    atr = (atr * (period - 1) + trs[i]) / period;
  }
  return atr;
}
