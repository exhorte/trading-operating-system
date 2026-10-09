/**
 * Golden vectors for the Python port of lib/analysis (migration phase 4).
 *
 * The TypeScript detectors are the reference; this script runs them over deterministic candle series and writes inputs AND outputs
 * to analysis.json, which `tests/unit/domain/market/analysis/test_golden.py` replays against the Python port with exact equality
 * (same IEEE-754 arithmetic on both sides, so a difference is a porting bug, never "noise").
 *
 * Run from 04_code, while lib/analysis still exists:
 *
 *     npx tsx python/tests/golden/generate_analysis_vectors.ts
 *
 * The generated file is the record of the original behaviour; after lib/analysis is deleted (phase 7) this script is history and
 * the JSON stays.
 */

import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { DEFAULT_ANALYSIS_CONFIG, DEFAULT_SESSION_WINDOWS, analyzeMarketContext, averageTrueRange } from "@/lib/analysis";
import type { AnalysisConfig } from "@/lib/analysis";
import { aggregateCandles } from "@/lib/analysis/aggregate";
import { computeBias, priceLocationOf } from "@/lib/analysis/bias";
import { detectLiquidity } from "@/lib/analysis/liquidity";
import { detectFairValueGaps, detectOrderBlocks } from "@/lib/analysis/pd-arrays";
import { sessionEnabled, sessionForTimestamp } from "@/lib/analysis/sessions";
import { detectStructureShifts, structuralBias } from "@/lib/analysis/structure";
import { detectSwings } from "@/lib/analysis/swings";
import { series } from "@/lib/analysis/test-helpers";
import type { Candle, SessionWindow } from "@/lib/domain/market";
import type { Timeframe } from "@/lib/domain/primitives";
import { walk } from "./support";

// ---------------------------------------------------------------------------------------------------- the cases

const GOLD: AnalysisConfig = DEFAULT_ANALYSIS_CONFIG;
const FX: AnalysisConfig = {
  ...DEFAULT_ANALYSIS_CONFIG,
  equalLevelTolerance: 0.0003,
  minFvgSize: 0.00004,
};
const lookback = (n: number, base: AnalysisConfig = GOLD): AnalysisConfig => ({ ...base, swingLookback: n });
const NO_SESSIONS: AnalysisConfig = {
  ...GOLD,
  sessionWindows: [{ session: "london", startUtc: "22:00", endUtc: "06:00", tradingEnabled: true }],
};

interface Case {
  name: string;
  symbol: string;
  timeframe: Timeframe;
  config: AnalysisConfig;
  candles: Candle[];
}

const MONDAY = "2026-01-05T00:00:00.000Z";

const cases: Case[] = [
  { name: "xau-m15-300", symbol: "XAUUSD", timeframe: "M15", config: GOLD,
    candles: walk({ seed: 1, n: 300, start: MONDAY, stepMinutes: 15, timeframe: "M15", symbol: "XAUUSD", startPrice: 4000, vol: 1.2, digits: 2, wave: 2.5, period: 23 }) },
  { name: "xau-m15-300-large-fvg", symbol: "XAUUSD", timeframe: "M15", config: { ...GOLD, minFvgSize: 0.8 },
    candles: walk({ seed: 12, n: 300, start: MONDAY, stepMinutes: 15, timeframe: "M15", symbol: "XAUUSD", startPrice: 4000, vol: 1.2, digits: 2, wave: 2.5, period: 25 }) },
  { name: "xau-m15-300-lookback1", symbol: "XAUUSD", timeframe: "M15", config: lookback(1),
    candles: walk({ seed: 2, n: 300, start: MONDAY, stepMinutes: 15, timeframe: "M15", symbol: "XAUUSD", startPrice: 4000, vol: 1.0, digits: 2, wave: 3, period: 31 }) },
  { name: "xau-m15-300-lookback3", symbol: "XAUUSD", timeframe: "M15", config: lookback(3),
    candles: walk({ seed: 3, n: 300, start: MONDAY, stepMinutes: 15, timeframe: "M15", symbol: "XAUUSD", startPrice: 4000, vol: 1.5, digits: 2, wave: 2, period: 17 }) },
  { name: "xau-m5-500-offstart", symbol: "XAUUSD", timeframe: "M5", config: GOLD,
    candles: walk({ seed: 4, n: 500, start: "2026-01-06T17:35:00.000Z", stepMinutes: 5, timeframe: "M5", symbol: "XAUUSD", startPrice: 3950, vol: 0.8, digits: 2, wave: 1.5, period: 40 }) },
  { name: "eurusd-m1-900", symbol: "EURUSDm", timeframe: "M1", config: FX,
    candles: walk({ seed: 5, n: 900, start: "2026-01-07T21:00:00.000Z", stepMinutes: 1, timeframe: "M1", symbol: "EURUSDm", startPrice: 1.085, vol: 0.00018, digits: 5, wave: 2, period: 55 }) },
  { name: "eurusd-m1-900-wide-tolerance", symbol: "EURUSDm", timeframe: "M1", config: { ...FX, equalLevelTolerance: 0.001, minFvgSize: 0.00003 },
    candles: walk({ seed: 6, n: 900, start: "2026-01-08T00:00:00.000Z", stepMinutes: 1, timeframe: "M1", symbol: "EURUSDm", startPrice: 1.172, vol: 0.00016, digits: 5, wave: 3, period: 70 }) },
  { name: "eurusd-h1-240", symbol: "EURUSDm", timeframe: "H1", config: lookback(2, FX),
    candles: walk({ seed: 7, n: 240, start: MONDAY, stepMinutes: 60, timeframe: "H1", symbol: "EURUSDm", startPrice: 1.1, vol: 0.0015, digits: 5, wave: 2.5, period: 19 }) },
  { name: "gbpusd-h4-180-forming-last", symbol: "GBPUSDm", timeframe: "H4", config: lookback(2, FX),
    candles: walk({ seed: 8, n: 180, start: MONDAY, stepMinutes: 240, timeframe: "H4", symbol: "GBPUSDm", startPrice: 1.27, vol: 0.004, digits: 5, wave: 2, period: 13, lastClosed: false }) },
  { name: "xau-d1-120", symbol: "XAUUSD", timeframe: "D1", config: GOLD,
    candles: walk({ seed: 9, n: 120, start: "2025-09-01T00:00:00.000Z", stepMinutes: 1440, timeframe: "D1", symbol: "XAUUSD", startPrice: 3800, vol: 25, digits: 2, wave: 2, period: 11 }) },
  { name: "xau-m15-300-custom-sessions", symbol: "XAUUSD", timeframe: "M15", config: NO_SESSIONS,
    candles: walk({ seed: 10, n: 300, start: "2026-01-09T12:00:00.000Z", stepMinutes: 15, timeframe: "M15", symbol: "XAUUSD", startPrice: 4050, vol: 1.1, digits: 2, wave: 2, period: 29 }) },
  { name: "coarse-prices-many-ties", symbol: "XAUUSD", timeframe: "M15", config: GOLD,
    candles: walk({ seed: 11, n: 300, start: MONDAY, stepMinutes: 15, timeframe: "M15", symbol: "XAUUSD", startPrice: 4000, vol: 1.2, digits: 0, wave: 2, period: 21 }) },
  // hand-built edge cases
  { name: "empty", symbol: "XAUUSD", timeframe: "M15", config: GOLD, candles: [] },
  { name: "one-candle", symbol: "XAUUSD", timeframe: "M15", config: GOLD, candles: series([[2000, 1990]]) },
  { name: "three-candles-bullish-gap", symbol: "XAUUSD", timeframe: "M15", config: GOLD, candles: series([[10, 9], [12, 10.5], [15, 13]]) },
  { name: "flat-equal-candles", symbol: "XAUUSD", timeframe: "M15", config: GOLD, candles: series(Array.from({ length: 40 }, () => [100, 99] as [number, number])) },
  { name: "strict-tie-highs", symbol: "XAUUSD", timeframe: "M15", config: GOLD,
    candles: series([[10, 8], [11, 9], [13, 10], [11, 9], [10, 8], [11, 9], [13, 10], [11, 9], [10, 8], [9, 7], [8, 6], [10, 8]]) },
];

const SWING_LOOKBACKS = [1, 2, 3];
const TOLERANCES = [0, 0.3, 2];
const ATR_PERIODS = [1, 3, 5, 14];

function perCase(c: Case) {
  const lastClose = c.candles.length ? c.candles[c.candles.length - 1].close : 0;
  const swings = Object.fromEntries(SWING_LOOKBACKS.map((n) => [String(n), detectSwings(c.candles, n)]));
  const structure = Object.fromEntries(
    SWING_LOOKBACKS.map((n) => {
      const shifts = detectStructureShifts(c.candles, detectSwings(c.candles, n), n);
      return [String(n), { shifts, bias: structuralBias(shifts), orderBlocks: detectOrderBlocks(c.candles, shifts) }];
    }),
  );
  const own = detectSwings(c.candles, c.config.swingLookback);
  return {
    name: c.name,
    symbol: c.symbol,
    timeframe: c.timeframe,
    config: c.config,
    candles: c.candles,
    swings,
    structure,
    liquidity: Object.fromEntries(
      TOLERANCES.map((t) => [String(t), detectLiquidity(c.candles, own, t)]),
    ),
    // the case's own minimum in full; a quarter of it (many small gaps) and five times it (few large ones) as digests
    fairValueGaps: {
      own: detectFairValueGaps(c.candles, c.config.minFvgSize),
      variants: Object.fromEntries(
        [c.config.minFvgSize / 4, c.config.minFvgSize * 5].map((m) => {
          const gaps = detectFairValueGaps(c.candles, m);
          return [
            String(m),
            {
              ids: gaps.map((g) => g.fvgId),
              directions: gaps.map((g) => g.direction),
              filledPercent: gaps.map((g) => g.filledPercent),
              mitigatedAt: gaps.map((g) => g.mitigatedAt),
            },
          ];
        }),
      ),
    },
    atr: Object.fromEntries(ATR_PERIODS.map((p) => [String(p), averageTrueRange(c.candles, p)])),
    priceLocation: priceLocationOf(lastClose, own),
    bias: computeBias(structuralBias(detectStructureShifts(c.candles, own, c.config.swingLookback))),
    context: analyzeMarketContext({ symbol: c.symbol, timeframe: c.timeframe, candles: c.candles, config: c.config }),
  };
}

// ---------------------------------------------------------------------------------------------------- sessions

const CUSTOM_WINDOWS: SessionWindow[] = [
  { session: "asia", startUtc: "21:30", endUtc: "03:15", tradingEnabled: false },
  { session: "london", startUtc: "03:15", endUtc: "09:00", tradingEnabled: true },
  { session: "new_york_am", startUtc: "13:00", endUtc: "13:00", tradingEnabled: true },
];

function sessionVectors() {
  const stamps: string[] = [];
  const t0 = Date.parse("2026-01-05T00:00:00.000Z");
  for (let m = 0; m < 24 * 60 * 2; m += 5) stamps.push(new Date(t0 + m * 60_000).toISOString());
  const windowsets = { default: DEFAULT_SESSION_WINDOWS, custom: CUSTOM_WINDOWS, none: [] as SessionWindow[] };
  return {
    stamps,
    windows: windowsets,
    sessions: Object.fromEntries(
      Object.entries(windowsets).map(([name, w]) => [name, stamps.map((s) => sessionForTimestamp(s, w))]),
    ),
    enabled: Object.fromEntries(
      Object.entries(windowsets).map(([name, w]) => [
        name,
        ["asia", "london", "new_york_am", "new_york_pm", "off_session"].map((s) => sessionEnabled(s as never, w)),
      ]),
    ),
  };
}

// ---------------------------------------------------------------------------------------------------- aggregation

function aggregateVectors() {
  const m1 = walk({ seed: 21, n: 1700, start: "2026-01-05T00:07:00.000Z", stepMinutes: 1, timeframe: "M1", symbol: "EURUSDm", startPrice: 1.085, vol: 0.00008, digits: 5, wave: 1, period: 60, lastClosed: false });
  const m5 = aggregateCandles(m1, "M1", "M5");
  const targets: Timeframe[] = ["M3", "M5", "M15", "M30", "H1", "H4", "D1", "W1"];
  return {
    m1,
    fromM1: Object.fromEntries(targets.map((t) => [t, aggregateCandles(m1, "M1", t)])),
    fromM5: Object.fromEntries((["M15", "H1", "H4", "D1"] as Timeframe[]).map((t) => [t, aggregateCandles(m5, "M5", t)])),
    empty: aggregateCandles([], "M1", "H1"),
  };
}

writeFileSync(
  join(__dirname, "analysis.json"),
  JSON.stringify({ cases: cases.map(perCase), sessions: sessionVectors(), aggregate: aggregateVectors() }),
);
console.log(`analysis.json written: ${cases.length} cases`);
