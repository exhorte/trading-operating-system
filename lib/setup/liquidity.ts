/**
 * S01 step 3 — liquidity map: PDH/PDL and equal highs/lows from
 * lib/analysis/liquidity.ts, plus Asia session high/low (not detected
 * anywhere in lib/analysis/), and selection of the trade's target and the
 * level a sweep is expected to trigger against.
 */

import type { Candle } from "@/lib/domain/market";
import type { SessionWindow } from "@/lib/domain/market";
import type { LiquidityKind, LiquidityLevel } from "@/lib/domain/analysis";
import type { Side } from "@/lib/domain/primitives";
import type { Swing } from "@/lib/analysis/types";
import { detectLiquidity } from "@/lib/analysis/liquidity";
import { sessionForTimestamp } from "@/lib/analysis/sessions";

const HIGH_SIDE_KINDS: LiquidityKind[] = ["previous_day_high", "session_high", "equal_highs", "buy_side"];
const LOW_SIDE_KINDS: LiquidityKind[] = ["previous_day_low", "session_low", "equal_lows", "sell_side"];

/**
 * High/low of the most recent contiguous Asia session found walking
 * backward from the end of `candles` — not an all-time min/max across every
 * Asia session in the series. `sweptAt` mirrors lib/analysis/liquidity.ts's
 * own (private, unexported) forward wick-scan: this file must not modify
 * lib/analysis/, so a small local copy is the alternative to reaching into
 * it.
 */
function asiaLevels(candles: Candle[], sessionWindows: SessionWindow[]): LiquidityLevel[] {
  let high = -Infinity;
  let low = Infinity;
  let lastAsiaIndex = -1;
  let collecting = false;

  for (let i = candles.length - 1; i >= 0; i -= 1) {
    const isAsia = sessionForTimestamp(candles[i].openTime, sessionWindows) === "asia";
    if (isAsia) {
      collecting = true;
      high = Math.max(high, candles[i].high);
      low = Math.min(low, candles[i].low);
      if (lastAsiaIndex === -1) lastAsiaIndex = i;
    } else if (collecting) {
      break; // walked out of the most recent Asia block
    }
  }
  if (lastAsiaIndex === -1) {
    return [];
  }

  const detectedAt = candles[Math.min(lastAsiaIndex + 1, candles.length - 1)].openTime;
  const { symbol, timeframe } = candles[0];
  const sweptAt = (price: number, side: "above" | "below"): string | null => {
    for (let t = lastAsiaIndex + 1; t < candles.length; t += 1) {
      if (side === "above" && candles[t].high > price) return candles[t].openTime;
      if (side === "below" && candles[t].low < price) return candles[t].openTime;
    }
    return null;
  };

  return [
    {
      levelId: `liq-session_high-${lastAsiaIndex}`,
      symbol,
      timeframe,
      kind: "session_high",
      price: high,
      sweptAt: sweptAt(high, "above"),
      detectedAt,
    },
    {
      levelId: `liq-session_low-${lastAsiaIndex}`,
      symbol,
      timeframe,
      kind: "session_low",
      price: low,
      sweptAt: sweptAt(low, "below"),
      detectedAt,
    },
  ];
}

/** PDH/PDL + equal highs/lows (lib/analysis/) plus Asia H/L, unified. */
export function liquidityPool(
  candles: Candle[],
  swings: Swing[],
  equalLevelTolerance: number,
  sessionWindows: SessionWindow[],
): LiquidityLevel[] {
  return [...detectLiquidity(candles, swings, equalLevelTolerance), ...asiaLevels(candles, sessionWindows)];
}

function nearestUnswept(
  pool: LiquidityLevel[],
  kinds: LiquidityKind[],
  fromPrice: number,
): LiquidityLevel | null {
  const candidates = pool.filter((l) => kinds.includes(l.kind) && l.sweptAt === null);
  if (candidates.length === 0) {
    return null;
  }
  return candidates.reduce((best, l) =>
    Math.abs(l.price - fromPrice) < Math.abs(best.price - fromPrice) ? l : best,
  );
}

/** The opposite, not-yet-purged pool the trade targets (S01: "la cible du
 * trade est la poche opposée non encore purgée"). Convention: nearest
 * unswept candidate — a repo convention like S01's own "liquidité interne",
 * adjustable after observation, not a rule stated numerically anywhere. */
export function opposingTarget(pool: LiquidityLevel[], side: Side, fromPrice: number): LiquidityLevel | null {
  return nearestUnswept(pool, side === "buy" ? HIGH_SIDE_KINDS : LOW_SIDE_KINDS, fromPrice);
}

/** The resting liquidity a sweep is expected to trigger against: opposite
 * side of `opposingTarget` (a buy sweeps low-side liquidity, then targets
 * high-side liquidity). Same nearest-candidate convention. */
export function sweepTriggerCandidate(pool: LiquidityLevel[], side: Side, fromPrice: number): LiquidityLevel | null {
  return nearestUnswept(pool, side === "buy" ? LOW_SIDE_KINDS : HIGH_SIDE_KINDS, fromPrice);
}
