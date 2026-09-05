/**
 * PD-array (Premium/Discount array) detection: fair value gaps and order blocks.
 *
 * Both are detected from strictly past candles at their formation bar; the
 * mitigation scan that follows uses only later candles, so a gap/block is never
 * labelled with information from before it existed (no look-ahead).
 */

import type { Candle } from "@/lib/domain/market";
import type { FairValueGap, OrderBlock, StructureShift } from "@/lib/domain/analysis";

function clampPercent(value: number): number {
  if (value < 0) return 0;
  if (value > 100) return 100;
  return Math.round(value * 10) / 10;
}

/**
 * Three-candle imbalance: a bullish FVG is a gap between candle[i-2].high and
 * candle[i].low; a bearish FVG is the mirror. Fill and mitigation are measured
 * from the candles that follow formation.
 */
export function detectFairValueGaps(candles: Candle[], minSize: number): FairValueGap[] {
  const gaps: FairValueGap[] = [];
  if (candles.length < 3) {
    return gaps;
  }
  const { symbol, timeframe } = candles[0];

  for (let i = 2; i < candles.length; i += 1) {
    const left = candles[i - 2];
    const right = candles[i];

    // Bullish gap: prior high below current low.
    if (right.low - left.high >= minSize) {
      const low = left.high;
      const high = right.low;
      gaps.push(
        finalizeGap(candles, i, { symbol, timeframe, direction: "bullish", high, low }),
      );
      continue;
    }
    // Bearish gap: prior low above current high.
    if (left.low - right.high >= minSize) {
      const low = right.high;
      const high = left.low;
      gaps.push(
        finalizeGap(candles, i, { symbol, timeframe, direction: "bearish", high, low }),
      );
    }
  }

  return gaps;
}

function finalizeGap(
  candles: Candle[],
  formedAt: number,
  base: Pick<FairValueGap, "symbol" | "timeframe" | "direction" | "high" | "low">,
): FairValueGap {
  const span = base.high - base.low;
  let filledPercent = 0;
  let mitigatedAt: string | null = null;

  for (let t = formedAt + 1; t < candles.length; t += 1) {
    const c = candles[t];
    const penetration =
      base.direction === "bullish" ? base.high - c.low : c.high - base.low;
    filledPercent = Math.max(filledPercent, clampPercent((penetration / span) * 100));
    if (filledPercent >= 100) {
      mitigatedAt = c.openTime;
      break;
    }
  }

  return {
    fvgId: `fvg-${formedAt}`,
    ...base,
    filledPercent,
    mitigatedAt,
    detectedAt: candles[formedAt].openTime,
  };
}

/**
 * Order block: the last opposing candle before a structure shift's
 * displacement. A bullish shift is preceded by the last down-candle (bullish
 * OB); a bearish shift by the last up-candle (bearish OB).
 */
export function detectOrderBlocks(
  candles: Candle[],
  shifts: StructureShift[],
): OrderBlock[] {
  const blocks: OrderBlock[] = [];
  if (candles.length === 0) {
    return blocks;
  }
  const { symbol, timeframe } = candles[0];
  const indexByTime = new Map(candles.map((c, i) => [c.openTime, i]));

  for (const shift of shifts) {
    const shiftIndex = indexByTime.get(shift.occurredAt);
    if (shiftIndex === undefined) {
      continue;
    }
    const wantsDownCandle = shift.direction === "bullish";
    let obIndex = -1;
    for (let k = shiftIndex - 1; k >= 0; k -= 1) {
      const opposing = wantsDownCandle
        ? candles[k].close < candles[k].open
        : candles[k].close > candles[k].open;
      if (opposing) {
        obIndex = k;
        break;
      }
    }
    if (obIndex === -1) {
      continue;
    }

    const ob = candles[obIndex];
    let mitigatedAt: string | null = null;
    for (let t = shiftIndex + 1; t < candles.length; t += 1) {
      if (candles[t].low <= ob.high && candles[t].high >= ob.low) {
        mitigatedAt = candles[t].openTime;
        break;
      }
    }

    blocks.push({
      orderBlockId: `ob-${obIndex}`,
      symbol,
      timeframe,
      direction: shift.direction,
      high: ob.high,
      low: ob.low,
      mitigatedAt,
      detectedAt: ob.openTime,
    });
  }

  return blocks;
}
