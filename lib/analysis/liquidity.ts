/**
 * Liquidity detection: equal highs/lows (relative-equal within tolerance),
 * previous-day high/low, and their swept state.
 *
 * A level is "swept" once a later candle's wick trades beyond it — the classic
 * draw-on-liquidity event. The sweep scan only looks forward from the bar that
 * established the level (no look-ahead).
 */

import type { Candle } from "@/lib/domain/market";
import type { LiquidityLevel, LiquidityKind } from "@/lib/domain/analysis";
import type { Swing } from "./types";

interface Cluster {
  price: number;
  formedAt: number;
  formedTime: string;
  members: number;
}

function clusterSwings(swings: Swing[], tolerance: number): Cluster[] {
  const clusters: Cluster[] = [];
  for (const swing of swings) {
    const hit = clusters.find((c) => Math.abs(c.price - swing.price) <= tolerance);
    if (hit) {
      hit.price = (hit.price * hit.members + swing.price) / (hit.members + 1);
      hit.members += 1;
      if (swing.index > hit.formedAt) {
        hit.formedAt = swing.index;
        hit.formedTime = swing.time;
      }
    } else {
      clusters.push({
        price: swing.price,
        formedAt: swing.index,
        formedTime: swing.time,
        members: 1,
      });
    }
  }
  return clusters;
}

function firstSweep(
  candles: Candle[],
  fromIndex: number,
  price: number,
  side: "above" | "below",
): string | null {
  for (let t = fromIndex + 1; t < candles.length; t += 1) {
    if (side === "above" && candles[t].high > price) {
      return candles[t].openTime;
    }
    if (side === "below" && candles[t].low < price) {
      return candles[t].openTime;
    }
  }
  return null;
}

export function detectLiquidity(
  candles: Candle[],
  swings: Swing[],
  tolerance: number,
): LiquidityLevel[] {
  const levels: LiquidityLevel[] = [];
  if (candles.length === 0) {
    return levels;
  }
  const { symbol, timeframe } = candles[0];

  const pushLevel = (
    kind: LiquidityKind,
    price: number,
    formedAt: number,
    detectedAt: string,
    side: "above" | "below",
  ) => {
    levels.push({
      levelId: `liq-${kind}-${formedAt}`,
      symbol,
      timeframe,
      kind,
      price: Math.round(price * 100) / 100,
      sweptAt: firstSweep(candles, formedAt, price, side),
      detectedAt,
    });
  };

  const highs = swings.filter((s) => s.kind === "high");
  const lows = swings.filter((s) => s.kind === "low");

  for (const cluster of clusterSwings(highs, tolerance)) {
    if (cluster.members >= 2) {
      pushLevel("equal_highs", cluster.price, cluster.formedAt, cluster.formedTime, "above");
    }
  }
  for (const cluster of clusterSwings(lows, tolerance)) {
    if (cluster.members >= 2) {
      pushLevel("equal_lows", cluster.price, cluster.formedAt, cluster.formedTime, "below");
    }
  }

  // Previous-day high/low become today's draw-on-liquidity targets.
  const dayKey = (c: Candle) => c.openTime.slice(0, 10);
  const lastDay = dayKey(candles[candles.length - 1]);
  const prevDayCandles = candles.filter((c) => dayKey(c) < lastDay);
  if (prevDayCandles.length > 0) {
    const prevDay = dayKey(prevDayCandles[prevDayCandles.length - 1]);
    const prior = prevDayCandles.filter((c) => dayKey(c) === prevDay);
    const pdh = Math.max(...prior.map((c) => c.high));
    const pdl = Math.min(...prior.map((c) => c.low));
    const todayStart = candles.findIndex((c) => dayKey(c) === lastDay);
    const detectedAt = candles[todayStart].openTime;
    pushLevel("previous_day_high", pdh, todayStart, detectedAt, "above");
    pushLevel("previous_day_low", pdl, todayStart, detectedAt, "below");
  }

  return levels;
}
