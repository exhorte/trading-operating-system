/**
 * Aggregates a lower-timeframe candle series into a higher one — EA-02's
 * worker fetches only M1 from MT5 and derives H1/H4/D1 from it in TS,
 * rather than issuing four separate MT5 queries per symbol. Buckets are
 * aligned to fixed UTC boundaries (epoch-relative), not to wherever the
 * input series happens to start, so the same M1 series always aggregates
 * to the same H1/H4/D1 bars regardless of the query window.
 *
 * New file, not a change to an existing lib/analysis/ detector.
 */

import type { Candle } from "@/lib/domain/market";
import type { Timeframe } from "@/lib/domain/primitives";

const TIMEFRAME_MINUTES: Record<Timeframe, number> = {
  M1: 1,
  M3: 3,
  M5: 5,
  M15: 15,
  M30: 30,
  H1: 60,
  H4: 240,
  D1: 1440,
  W1: 10_080,
};

function bucketStartMs(openTimeMs: number, targetMinutes: number): number {
  const targetMs = targetMinutes * 60_000;
  return Math.floor(openTimeMs / targetMs) * targetMs;
}

/**
 * `source` must be chronological and all on `sourceTimeframe`; `sourceTimeframe`
 * must divide evenly into `targetTimeframe` (e.g. M1 into H1, not M1 into a
 * timeframe that isn't a whole multiple of a minute — every entry in
 * `Timeframe` qualifies). A bucket is `closed` only once it holds every
 * expected source candle AND the last of them is itself closed — a partial
 * or still-forming bucket is still emitted (as the trailing, forming bar),
 * consistent with how the live feed always includes one forming bar.
 */
export function aggregateCandles(
  source: Candle[],
  sourceTimeframe: Timeframe,
  targetTimeframe: Timeframe,
): Candle[] {
  if (source.length === 0) {
    return [];
  }
  const sourceMinutes = TIMEFRAME_MINUTES[sourceTimeframe];
  const targetMinutes = TIMEFRAME_MINUTES[targetTimeframe];
  const expectedMembers = targetMinutes / sourceMinutes;

  const buckets: Candle[] = [];
  let currentBucketStartMs = -1;
  let members = 0;

  for (const candle of source) {
    const openMs = Date.parse(candle.openTime);
    const bucketMs = bucketStartMs(openMs, targetMinutes);

    if (bucketMs !== currentBucketStartMs) {
      currentBucketStartMs = bucketMs;
      members = 0;
      buckets.push({
        symbol: candle.symbol,
        timeframe: targetTimeframe,
        openTime: new Date(bucketMs).toISOString(),
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
        volume: 0, // accumulated uniformly below, including this first candle
        closed: false,
      });
    }

    const bucket = buckets[buckets.length - 1];
    bucket.high = Math.max(bucket.high, candle.high);
    bucket.low = Math.min(bucket.low, candle.low);
    bucket.close = candle.close;
    bucket.volume += candle.volume;
    members += 1;
    bucket.closed = members >= expectedMembers && candle.closed;
  }

  return buckets;
}
