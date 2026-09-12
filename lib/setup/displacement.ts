/**
 * S01 step 5 — displacement and MSS on M1: a candle body must close beyond
 * the last opposite swing, with an accompanying unfilled FVG, and a body of
 * at least 1.5 x ATR(14). "Une mèche qui traverse ne vaut rien" is handled
 * by construction: the break test compares to `close`, not `high`/`low`, so
 * a wick beyond the swing with a close that falls back never qualifies.
 *
 * Reuses lib/analysis/atr.ts and lib/analysis/pd-arrays.ts as-is; the only
 * new logic is the composed rule (body size + FVG + body-close break).
 */

import type { Candle } from "@/lib/domain/market";
import type { FairValueGap } from "@/lib/domain/analysis";
import type { Bias, Side, UtcTimestamp } from "@/lib/domain/primitives";
import { averageTrueRange } from "@/lib/analysis/atr";
import { detectFairValueGaps } from "@/lib/analysis/pd-arrays";

export interface DisplacementEvent {
  occurredAt: UtcTimestamp;
  brokenSwingPrice: number;
  fairValueGap: FairValueGap;
  bodySize: number;
  atr: number;
}

export interface DisplacementConfig {
  atrPeriod: number;
  minBodyAtrMultiple: number;
  minFvgSize: number;
}

function sideToBias(side: Side): Bias {
  return side === "buy" ? "bullish" : "bearish";
}

/**
 * `candles` should be the entry-timeframe series up to and including the
 * bars searched (typically everything from the sweep onward). Only bars up
 * to the candle under test are used for ATR/FVG at that bar — no
 * look-ahead.
 */
export function detectDisplacement(
  candles: Candle[],
  side: Side,
  oppositeSwingPrice: number,
  config: DisplacementConfig,
): DisplacementEvent | null {
  for (let i = 2; i < candles.length; i += 1) {
    const c = candles[i];
    const brokeBody = side === "buy" ? c.close > oppositeSwingPrice : c.close < oppositeSwingPrice;
    if (!brokeBody) {
      continue;
    }

    const bodySize = Math.abs(c.close - c.open);
    const atr = averageTrueRange(candles.slice(0, i + 1), config.atrPeriod);
    if (atr <= 0 || bodySize < config.minBodyAtrMultiple * atr) {
      continue; // body too small relative to volatility -> not a real displacement
    }

    const gaps = detectFairValueGaps(candles.slice(0, i + 1), config.minFvgSize);
    const gap = gaps.find(
      (g) => g.detectedAt === c.openTime && g.direction === sideToBias(side) && g.mitigatedAt === null,
    );
    if (!gap) {
      continue; // no accompanying unfilled FVG on this candle
    }

    return { occurredAt: c.openTime, brokenSwingPrice: oppositeSwingPrice, fairValueGap: gap, bodySize, atr };
  }
  return null;
}
