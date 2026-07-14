/**
 * Segmented diagnostics over backtest trades (Phase 12, ADR 0013). Pure.
 *
 * Groups trades by a dimension and computes per-bucket metrics so the sources
 * of losses can be located BEFORE any rule changes. Buckets below MIN_BUCKET_N
 * trades are flagged non-informative — with 13 dimensions, small buckets WILL
 * look significant by chance; only strong, explainable effects count.
 */

import { computeMetrics, type BacktestMetrics } from "./metrics";
import type { SimulatedTrade, TradeOutcome } from "./outcome";

/** Minimum trades for a bucket to be considered informative. */
export const MIN_BUCKET_N = 30;

/** One analyzed trade row: outcome fields + frozen features + split tag. */
export interface DiagTrade {
  signalTime: string;
  side: string;
  outcome: TradeOutcome;
  bothTouch: boolean;
  rMultiple: number;
  barsHeld: number;
  score: number;
  stopLoss: number;
  entryPrice: number;
  split: string;
  features: Record<string, unknown>;
}

export interface SegmentStat {
  bucket: string;
  n: number;
  winRate: number;
  expectancyR: number;
  cumulativeR: number;
  /** n < MIN_BUCKET_N — do not act on this bucket alone. */
  lowSample: boolean;
}

function toSimulated(t: DiagTrade): SimulatedTrade {
  return {
    outcome: t.outcome,
    rMultiple: t.rMultiple,
    barsHeld: t.barsHeld,
    exitPrice: 0,
    bothTouch: t.bothTouch,
  };
}

function stat(bucket: string, trades: DiagTrade[]): SegmentStat {
  const m: BacktestMetrics = computeMetrics(trades.map(toSimulated));
  return {
    bucket,
    n: m.tradeCount,
    winRate: m.winRate,
    expectancyR: m.expectancyR,
    cumulativeR: m.cumulativeR,
    lowSample: m.tradeCount < MIN_BUCKET_N,
  };
}

/** Group by a single-valued key; buckets sorted by cumulative R ascending
 *  (worst first — this is a loss hunt). */
export function segmentBy(
  trades: DiagTrade[],
  key: (t: DiagTrade) => string,
): SegmentStat[] {
  const groups = new Map<string, DiagTrade[]>();
  for (const t of trades) {
    const bucket = key(t);
    const list = groups.get(bucket);
    if (list) {
      list.push(t);
    } else {
      groups.set(bucket, [t]);
    }
  }
  return [...groups.entries()]
    .map(([bucket, list]) => stat(bucket, list))
    .sort((a, b) => a.cumulativeR - b.cumulativeR);
}

/** Group by a multi-valued key (e.g. liquidity kinds): one trade may count in
 *  several buckets, so bucket sums exceed the total — stated in the report. */
export function segmentByMulti(
  trades: DiagTrade[],
  keys: (t: DiagTrade) => string[],
): SegmentStat[] {
  const groups = new Map<string, DiagTrade[]>();
  for (const t of trades) {
    const buckets = keys(t);
    for (const bucket of buckets.length > 0 ? buckets : ["(none)"]) {
      const list = groups.get(bucket);
      if (list) {
        list.push(t);
      } else {
        groups.set(bucket, [t]);
      }
    }
  }
  return [...groups.entries()]
    .map(([bucket, list]) => stat(bucket, list))
    .sort((a, b) => a.cumulativeR - b.cumulativeR);
}

// --- standard dimension extractors (feature keys per ADR 0013) ---

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function feature(t: DiagTrade, key: string): string {
  const v = t.features[key];
  return v === undefined || v === null ? "(missing)" : String(v);
}

export const DIMENSIONS: Record<string, (t: DiagTrade) => string> = {
  side: (t) => t.side,
  session: (t) => feature(t, "session"),
  dayOfWeek: (t) => DOW[new Date(t.signalTime).getUTCDay()],
  month: (t) => t.signalTime.slice(0, 7),
  bias: (t) => feature(t, "bias"),
  sideVsBias: (t) => feature(t, "sideVsBias"),
  structure: (t) => feature(t, "structure"),
  score: (t) => `score ${t.score}`,
  stopDistance: (t) => {
    const d = Math.abs(t.entryPrice - t.stopLoss);
    return d < 4 ? "3.5" : d < 5.5 ? "5.0" : d < 7 ? "6.5" : "8.0";
  },
  duration: (t) =>
    t.barsHeld <= 2 ? "1-2 bars" : t.barsHeld <= 8 ? "3-8 bars" : t.barsHeld <= 20 ? "9-20 bars" : "21+ bars",
  outcome: (t) => t.outcome,
  bothTouch: (t) => (t.bothTouch ? "both-touch" : "clean"),
  fvgInside: (t) => (feature(t, "fvgInside") === "true" ? "inside FVG" : "outside FVG"),
  obInside: (t) => (feature(t, "obInside") === "true" ? "inside OB" : "outside OB"),
};

export const MULTI_DIMENSIONS: Record<string, (t: DiagTrade) => string[]> = {
  liquidityKind: (t) => (Array.isArray(t.features.liqKinds) ? (t.features.liqKinds as string[]) : []),
};
