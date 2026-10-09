/**
 * Golden vectors for the Python port of lib/setup — strategy S01 (migration phase 5).
 *
 * Runs the TypeScript original over deterministic inputs and writes inputs AND outputs to s01.json, which
 * `tests/unit/domain/s01/test_golden.py` replays against the Python port with exact equality. Three families:
 *
 *  - unit vectors for every step (bias, dealing range, liquidity map, sweep, displacement, point of interest, stop, gates);
 *  - end-to-end scenarios for evaluateSetup: the fixture of lib/setup/proposal.test.ts (a complete buy), its mirror (a complete sell),
 *    a ladder of single-fault variants (one per stage the pipeline can stop at), and perturbed copies with random parameters;
 *  - the calendar-dependent and agreement helpers (killzones across both DST changes, setup/trade reconciliation).
 *
 * Run from 04_code, while lib/setup still exists:
 *
 *     npx tsx python/tests/golden/generate_s01_vectors.ts
 */

import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { DEFAULT_SESSION_WINDOWS } from "@/lib/analysis/config";
import { candleAt, series } from "@/lib/analysis/test-helpers";
import type { Candle } from "@/lib/domain/market";
import type { Side } from "@/lib/domain/primitives";
import { dailyBias } from "@/lib/setup/bias";
import { lastDealingRange, locationInRange } from "@/lib/setup/dealing-range";
import { detectDisplacement } from "@/lib/setup/displacement";
import { evaluateViabilityGates } from "@/lib/setup/gates";
import { liquidityPool, opposingTarget, sweepTriggerCandidate } from "@/lib/setup/liquidity";
import { isInvalidatedByCe, pointOfInterestFor } from "@/lib/setup/poi";
import { isInKillzone, isPastNyLunch } from "@/lib/setup/preconditions";
import { evaluateSetup, type SetupProposalInput } from "@/lib/setup/proposal";
import { reconcile } from "@/lib/setup/reconciliation";
import { computeStopLoss } from "@/lib/setup/stop";
import { detectSweep } from "@/lib/setup/sweep";
import { detectSwings } from "@/lib/analysis/swings";
import { mulberry32, walk } from "./support";

const round2 = (x: number) => Math.round(x * 100) / 100;

/** Candles are written as rows to keep the file small: { s: symbol, tf: timeframe, rows: [openTime, o, h, l, c, volume, closed] }. */
interface PackedCandles {
  s: string;
  tf: string;
  rows: Array<[string, number, number, number, number, number, 0 | 1]>;
}
const pack = (cs: Candle[], fallback: { s: string; tf: string } = { s: "EURUSD", tf: "M1" }): PackedCandles => ({
  s: cs.length ? cs[0].symbol : fallback.s,
  tf: cs.length ? cs[0].timeframe : fallback.tf,
  rows: cs.map((c) => [c.openTime, c.open, c.high, c.low, c.close, c.volume, c.closed ? 1 : 0]),
});
const packInput = (i: SetupProposalInput) => ({
  ...i,
  h4Candles: pack(i.h4Candles),
  d1Candles: pack(i.d1Candles),
  h1Candles: pack(i.h1Candles),
  contextCandles: pack(i.contextCandles),
  reactionCandles: pack(i.reactionCandles),
});
const pick = <T>(rand: () => number, items: T[]): T => items[Math.floor(rand() * items.length)];

// ---------------------------------------------------------------------------------------------------- the reference scenario
// (lib/setup/proposal.test.ts, verbatim)

const bullishHtf = series([
  { high: 10, low: 8, close: 9 },
  { high: 12, low: 9, close: 11 },
  { high: 11, low: 9, close: 10 },
  { high: 13, low: 10, close: 12.5 },
]);
const bearishHtf = series([
  { high: 12, low: 10, close: 11 },
  { high: 11, low: 8, close: 9 },
  { high: 11, low: 9, close: 10 },
  { high: 10, low: 7, close: 7.5 },
]);
const h1Discount = series([
  { high: 10, low: 9, close: 9.5 },
  { high: 9, low: 8, close: 8.5 },
  { high: 10, low: 9, close: 9.5 },
  { high: 12, low: 10, close: 11 },
  { high: 10, low: 9, close: 9.5 },
]);
const h1Premium = series([
  { high: 10, low: 9, close: 9.5 },
  { high: 9, low: 8, close: 8.5 },
  { high: 10, low: 9, close: 9.5 },
  { high: 12, low: 10, close: 11 },
  { high: 10, low: 9, close: 9.5 },
  { high: 12, low: 11, close: 11.5 },
]);
const at = (i: number, high: number, low: number, opts: { open?: number; close?: number } = {}) =>
  candleAt(420 + i, high, low, { ...opts, stepMinutes: 1, symbol: "EURUSD" });
const contextCandles = [
  at(0, 103.0, 102.5, { close: 102.8 }),
  at(1, 105.0, 102.6, { close: 102.9 }),
  at(2, 102.9, 102.4, { close: 102.6 }),
  at(3, 102.5, 101.0, { close: 101.5 }),
  at(4, 105.0, 101.2, { close: 101.5 }),
  at(5, 102.0, 100.0, { close: 100.2 }),
  at(6, 100.5, 99.0, { close: 99.3 }),
  at(7, 100.3, 99.5, { close: 99.8 }),
  at(8, 100.2, 99.6, { close: 100.0 }),
  at(9, 100.4, 99.0, { close: 99.4 }),
  at(10, 100.7, 99.7, { close: 100.3 }),
  at(11, 100.9, 99.8, { close: 100.5 }),
  at(12, 100.6, 99.85, { close: 100.3 }),
];
const reactionCandles = [
  at(13, 99.4, 98.7, { close: 99.2 }),
  at(14, 99.5, 99.0, { open: 99.3, close: 99.3 }),
  at(15, 99.7, 99.2, { open: 99.5, close: 99.5 }),
  at(16, 99.9, 99.4, { open: 99.6, close: 99.6 }),
  at(17, 110.3, 100.0, { open: 100.0, close: 110.0 }),
];

function baseInput(): SetupProposalInput {
  return {
    symbol: "EURUSD",
    h4Candles: bullishHtf,
    d1Candles: bullishHtf,
    h1Candles: h1Discount,
    contextCandles,
    reactionCandles,
    swingLookback: 1,
    equalLevelTolerance: 0.3,
    sessionWindows: DEFAULT_SESSION_WINDOWS,
    atrPeriod: 14,
    minBodyAtrMultiple: 1.5,
    minFvgSize: 0.2,
    spreadBuffer: 0.05,
    spread: 0.1,
    commission: 0.02,
    costThreshold: 0.25,
    minRiskReward: 3,
  };
}

/** The same scene upside down around 200: highs become lows, a buy becomes a sell. */
const PIVOT = 200;
const mirrorCandle = (c: Candle): Candle => ({
  ...c,
  open: PIVOT - c.open,
  high: PIVOT - c.low,
  low: PIVOT - c.high,
  close: PIVOT - c.close,
});
function mirrored(input: SetupProposalInput): SetupProposalInput {
  const m = (cs: Candle[]) => cs.map(mirrorCandle);
  return {
    ...input,
    h4Candles: m(input.h4Candles),
    d1Candles: m(input.d1Candles),
    h1Candles: m(input.h1Candles),
    contextCandles: m(input.contextCandles),
    reactionCandles: m(input.reactionCandles),
  };
}

// ---------------------------------------------------------------------------------------------------- single-fault variants

const faults: Array<[string, (b: SetupProposalInput) => SetupProposalInput]> = [
  ["base", (b) => b],
  ["htf-disagree", (b) => ({ ...b, d1Candles: bearishHtf })],
  ["htf-empty", (b) => ({ ...b, h4Candles: [], d1Candles: [] })],
  ["h1-premium", (b) => ({ ...b, h1Candles: h1Premium })],
  ["h1-empty", (b) => ({ ...b, h1Candles: [] })],
  ["h1-one-candle", (b) => ({ ...b, h1Candles: h1Discount.slice(0, 1) })],
  ["context-short", (b) => ({ ...b, contextCandles: contextCandles.slice(0, 2) })],
  ["context-empty", (b) => ({ ...b, contextCandles: [] })],
  ["no-sweep", (b) => ({ ...b, reactionCandles: reactionCandles.map((c) => ({ ...c, low: 99.5, high: Math.max(c.high, 99.6) })) })],
  ["no-reaction", (b) => ({ ...b, reactionCandles: [] })],
  ["cassure-no-reclaim", (b) => ({ ...b, reactionCandles: [{ ...reactionCandles[0], close: 98.9 }, ...reactionCandles.slice(1)] })],
  ["no-displacement", (b) => ({ ...b, reactionCandles: [reactionCandles[0], ...reactionCandles.slice(1).map((c) => ({ ...c, close: 99.5, open: 99.4, high: 99.6 }))] })],
  ["body-too-small", (b) => ({ ...b, minBodyAtrMultiple: 100 })],
  ["fvg-too-small-to-count", (b) => ({ ...b, minFvgSize: 100 })],
  ["stop-over-ceiling", (b) => ({ ...b, maxStopDistance: 0.5 })],
  ["stop-under-ceiling", (b) => ({ ...b, maxStopDistance: 5 })],
  ["cost-gate", (b) => ({ ...b, spread: 5, commission: 5 })],
  ["cost-threshold-tiny", (b) => ({ ...b, costThreshold: 0.01 })],
  ["rr-gate", (b) => ({ ...b, minRiskReward: 50 })],
  ["rr-exactly-near", (b) => ({ ...b, minRiskReward: 3.5 })],
  ["no-spread-buffer", (b) => ({ ...b, spreadBuffer: 0 })],
  ["lookback-2", (b) => ({ ...b, swingLookback: 2 })],
  ["atr-period-3", (b) => ({ ...b, atrPeriod: 3 })],
];

// ---------------------------------------------------------------------------------------------------- no swing to break

/** A context entirely inside the Asia window with strictly falling highs and lows: session levels exist (target and trigger), but no
 * swing high — so a sweep is found and the pipeline stops at the opposite swing. */
function asiaDrift(): SetupProposalInput {
  const context = Array.from({ length: 13 }, (_, i) =>
    candleAt(180 + i, 105 - i * 0.5, 104 - i * 0.5 - 0.1, { stepMinutes: 1, symbol: "EURUSD", close: 104.5 - i * 0.5 }),
  );
  const lastLow = context[context.length - 1].low;
  const reaction = [
    candleAt(193, lastLow + 0.3, lastLow - 0.2, { stepMinutes: 1, symbol: "EURUSD", open: lastLow, close: lastLow + 0.1 }),
    candleAt(194, lastLow + 0.4, lastLow, { stepMinutes: 1, symbol: "EURUSD", open: lastLow + 0.1, close: lastLow + 0.3 }),
  ];
  return { ...baseInput(), contextCandles: context, reactionCandles: reaction, swingLookback: 1 };
}

// ---------------------------------------------------------------------------------------------------- perturbed copies

function jitter(c: Candle, rand: () => number, amount: number): Candle {
  const d = (rand() - 0.5) * 2 * amount;
  const e = (rand() - 0.5) * 2 * amount;
  const open = round2(c.open + d);
  const close = round2(c.close + e);
  const high = round2(Math.max(c.high + (rand() - 0.5) * 2 * amount, open, close));
  const low = round2(Math.min(c.low + (rand() - 0.5) * 2 * amount, open, close));
  return { ...c, open, high, low, close };
}

function perturbed(seed: number): { name: string; input: SetupProposalInput } {
  const rand = mulberry32(seed);
  const amount = pick(rand, [0.02, 0.05, 0.1, 0.2, 0.4]);
  const sell = rand() < 0.5;
  const base = sell ? mirrored(baseInput()) : baseInput();
  const j = (cs: Candle[]) => cs.map((c) => jitter(c, rand, amount));
  const input: SetupProposalInput = {
    ...base,
    h4Candles: base.h4Candles,
    d1Candles: base.d1Candles,
    h1Candles: rand() < 0.3 ? j(base.h1Candles) : base.h1Candles,
    contextCandles: j(base.contextCandles),
    reactionCandles: j(base.reactionCandles),
    swingLookback: pick(rand, [1, 1, 2]),
    equalLevelTolerance: pick(rand, [0.1, 0.3, 0.6]),
    atrPeriod: pick(rand, [3, 5, 14]),
    minBodyAtrMultiple: pick(rand, [0.5, 1.5, 3]),
    minFvgSize: pick(rand, [0.05, 0.2, 0.5]),
    spreadBuffer: pick(rand, [0, 0.02, 0.05, 0.2]),
    spread: pick(rand, [0, 0.02, 0.1, 0.3]),
    commission: pick(rand, [0, 0.02, 0.1]),
    costThreshold: pick(rand, [0.1, 0.25, 0.5]),
    minRiskReward: pick(rand, [1, 3, 5]),
    maxStopDistance: pick(rand, [undefined, 0.5, 1.5, 3]),
  };
  return { name: `perturbed-${seed}-${sell ? "sell" : "buy"}`, input };
}

// ---------------------------------------------------------------------------------------------------- random-walk scenarios

function randomScenario(seed: number): { name: string; input: SetupProposalInput } {
  const rand = mulberry32(seed);
  const start = pick(rand, ["2026-01-06T03:00:00.000Z", "2026-01-07T05:30:00.000Z", "2026-01-08T21:15:00.000Z", "2026-01-09T10:00:00.000Z"]);
  const price = 1.1 + rand() * 0.05;
  const vol = 0.0002 + rand() * 0.0004;
  const common = { symbol: "EURUSD", digits: 5 };
  const trend = 1 + rand() * 2;
  const h4 = walk({ ...common, seed: seed * 7 + 1, n: 40, start: "2025-12-20T00:00:00.000Z", stepMinutes: 240, timeframe: "H4", startPrice: price, vol: vol * 8, wave: trend, period: 5 + Math.floor(rand() * 8) });
  const d1 = walk({ ...common, seed: seed * 7 + 2, n: 30, start: "2025-12-01T00:00:00.000Z", stepMinutes: 1440, timeframe: "D1", startPrice: price, vol: vol * 16, wave: trend, period: 4 + Math.floor(rand() * 8) });
  const h1 = walk({ ...common, seed: seed * 7 + 3, n: 80, start: "2026-01-02T00:00:00.000Z", stepMinutes: 60, timeframe: "H1", startPrice: price, vol: vol * 4, wave: 2, period: 6 + Math.floor(rand() * 10) });
  const context = walk({ ...common, seed: seed * 7 + 4, n: 150, start, stepMinutes: 1, timeframe: "M1", startPrice: price, vol, wave: 2, period: 10 + Math.floor(rand() * 20) });
  const reactionStart = new Date(Date.parse(start) + 150 * 60_000).toISOString();
  const reaction = walk({ ...common, seed: seed * 7 + 5, n: 30, start: reactionStart, stepMinutes: 1, timeframe: "M1", startPrice: context[context.length - 1].close, vol: vol * 1.5, wave: 0, period: 10 });
  const input: SetupProposalInput = {
    symbol: "EURUSD",
    h4Candles: h4,
    d1Candles: d1,
    h1Candles: h1,
    contextCandles: context,
    reactionCandles: reaction,
    swingLookback: pick(rand, [1, 2]),
    equalLevelTolerance: 0.0003,
    sessionWindows: DEFAULT_SESSION_WINDOWS,
    atrPeriod: 14,
    minBodyAtrMultiple: 1.5,
    minFvgSize: 0.0001,
    spreadBuffer: 0.0001,
    spread: 0.00008,
    commission: 0.00002,
    costThreshold: 0.25,
    minRiskReward: 3,
  };
  return { name: `walk-${seed}`, input };
}

// ---------------------------------------------------------------------------------------------------- unit vectors

const SIDES: Side[] = ["buy", "sell"];

function unitSeries(seed: number, n: number, opts: Partial<Parameters<typeof walk>[0]> = {}): Candle[] {
  const rand = mulberry32(seed);
  return walk({
    seed,
    n,
    start: pick(rand, ["2026-01-05T00:00:00.000Z", "2026-01-06T19:40:00.000Z", "2026-01-07T05:20:00.000Z"]),
    stepMinutes: pick(rand, [1, 5, 15, 60]),
    timeframe: "M1",
    symbol: "EURUSD",
    startPrice: 1.1,
    vol: 0.0004 + rand() * 0.0006,
    digits: 5,
    wave: rand() * 3,
    period: 4 + Math.floor(rand() * 12),
    ...opts,
  });
}

function biasVectors() {
  return Array.from({ length: 60 }, (_, i) => {
    const rand = mulberry32(1000 + i);
    const lookback = pick(rand, [1, 2]);
    const h4 = unitSeries(2000 + i, 5 + Math.floor(rand() * 40), { timeframe: "H4", stepMinutes: 240 });
    const d1 = rand() < 0.5 ? h4 : unitSeries(3000 + i, 5 + Math.floor(rand() * 40), { timeframe: "D1", stepMinutes: 1440 });
    return { lookback, h4: pack(h4), d1: pack(d1), bias: dailyBias(h4, d1, lookback) };
  });
}

function dealingRangeVectors() {
  return Array.from({ length: 70 }, (_, i) => {
    const rand = mulberry32(4000 + i);
    const lookback = pick(rand, [1, 2, 3]);
    const candles = unitSeries(5000 + i, Math.floor(rand() * 60), { timeframe: "H1", stepMinutes: 60 });
    const range = lastDealingRange(candles, lookback);
    const last = candles.length ? candles[candles.length - 1].close : 1.1;
    const probes = range
      ? [last, range.equilibrium, range.equilibrium + 1e-9, range.equilibrium - 1e-9, range.externalHigh, range.externalLow]
      : [last];
    return {
      lookback,
      candles: pack(candles),
      range,
      locations: probes.map((price) => (range ? { price, location: locationInRange(price, range) } : null)),
      degenerate: locationInRange(1.1, { externalHigh: 1.1, externalLow: 1.1, equilibrium: 1.1 }),
    };
  });
}

function liquidityVectors() {
  return Array.from({ length: 30 }, (_, i) => {
    const rand = mulberry32(6000 + i);
    const lookback = pick(rand, [1, 2]);
    const tolerance = pick(rand, [0.0001, 0.0003, 0.001]);
    // spans a night: Asia blocks (23:00-07:00 UTC) appear in the middle of the series
    const candles = unitSeries(7000 + i, 100 + Math.floor(rand() * 200), {
      stepMinutes: pick(rand, [15, 30, 60]),
      start: pick(rand, ["2026-01-05T15:00:00.000Z", "2026-01-06T20:00:00.000Z", "2026-01-07T02:15:00.000Z"]),
    });
    const swings = detectSwings(candles, lookback);
    const pool = liquidityPool(candles, swings, tolerance, DEFAULT_SESSION_WINDOWS);
    const last = candles[candles.length - 1].close;
    const probes = [last, last - 0.003, last + 0.003];
    return {
      lookback,
      tolerance,
      candles: pack(candles),
      pool,
      targets: probes.flatMap((from) => SIDES.map((side) => ({ from, side, target: opposingTarget(pool, side, from), trigger: sweepTriggerCandidate(pool, side, from) }))),
    };
  });
}

function sweepVectors() {
  return Array.from({ length: 60 }, (_, i) => {
    const rand = mulberry32(8000 + i);
    const candles = unitSeries(9000 + i, 5 + Math.floor(rand() * 40));
    const mid = candles[Math.floor(rand() * candles.length)];
    const side = pick(rand, SIDES);
    const level = { kind: pick(rand, ["equal_lows", "equal_highs", "previous_day_low", "session_high"] as const), price: round5(mid.close + (rand() - 0.5) * 0.001) };
    return { candles: pack(candles), level, side, sweep: detectSweep(candles, level, side) };
  });
}
function round5(x: number) {
  return Math.round(x * 1e5) / 1e5;
}

function displacementVectors() {
  const out: Array<Record<string, unknown>> = [];
  for (let i = 0; i < 70; i += 1) {
    const rand = mulberry32(10000 + i);
    const candles = unitSeries(11000 + i, 6 + Math.floor(rand() * 50), { vol: 0.0006 + rand() * 0.0012 });
    const side = pick(rand, SIDES);
    const pivot = candles[Math.floor(rand() * candles.length)];
    const opposite = round5(side === "buy" ? pivot.close - rand() * 0.0006 : pivot.close + rand() * 0.0006);
    const config = { atrPeriod: pick(rand, [3, 5, 14]), minBodyAtrMultiple: pick(rand, [0.4, 1, 1.5]), minFvgSize: pick(rand, [0.00002, 0.0001, 0.0003]) };
    out.push({ candles: pack(candles), side, opposite, config, displacement: detectDisplacement(candles, side, opposite, config) });
  }
  // the reference scenario's own displacement, with and without the order-block fallback inputs
  const post = reactionCandles.slice(1);
  out.push({ candles: pack(post), side: "buy", opposite: 100.9, config: { atrPeriod: 14, minBodyAtrMultiple: 1.5, minFvgSize: 0.2 }, displacement: detectDisplacement(post, "buy", 100.9, { atrPeriod: 14, minBodyAtrMultiple: 1.5, minFvgSize: 0.2 }) });
  return out;
}

function poiVectors() {
  const out: Array<Record<string, unknown>> = [];
  const fvg = (rand: () => number, mitigated: boolean, direction: "bullish" | "bearish") => {
    const low = round5(1.1 + rand() * 0.01);
    const high = round5(low + 0.0002 + rand() * 0.001);
    return {
      fvgId: "fvg-1", symbol: "EURUSD", timeframe: "M1", direction, high, low, filledPercent: mitigated ? 100 : 0,
      mitigatedAt: mitigated ? "2026-01-05T09:30:00.000Z" : null, detectedAt: "2026-01-05T09:00:00.000Z",
    };
  };
  for (let i = 0; i < 80; i += 1) {
    const rand = mulberry32(12000 + i);
    const side = pick(rand, SIDES);
    const direction = side === "buy" ? "bullish" : "bearish";
    const displacement = {
      occurredAt: "2026-01-05T09:00:00.000Z", brokenSwingPrice: 1.1, fairValueGap: fvg(rand, rand() < 0.5, direction),
      bodySize: 0.001, atr: 0.0004,
    };
    const orderBlocks = Array.from({ length: Math.floor(rand() * 5) }, (_, k) => {
      const low = round5(1.1 + rand() * 0.01);
      return {
        orderBlockId: `ob-${k}`, symbol: "EURUSD", timeframe: "M1", direction: pick(rand, ["bullish", "bearish"]), high: round5(low + 0.0004),
        low, mitigatedAt: rand() < 0.4 ? "2026-01-05T09:40:00.000Z" : null,
        detectedAt: pick(rand, ["2026-01-05T08:00:00.000Z", "2026-01-05T08:30:00.000Z", "2026-01-05T09:00:00.000Z", "2026-01-05T09:20:00.000Z"]),
      };
    });
    const poi = pointOfInterestFor(displacement as never, orderBlocks as never, side);
    const after = unitSeries(13000 + i, Math.floor(rand() * 10));
    const probe = poi ?? { kind: "fvg" as const, high: 1.11, low: 1.1, ce: 1.105, formedAt: "x" };
    out.push({ side, displacement, orderBlocks, poi, after: pack(after), invalidated: isInvalidatedByCe(probe, side, after) });
  }
  return out;
}

function stopVectors() {
  return Array.from({ length: 80 }, (_, i) => {
    const rand = mulberry32(14000 + i);
    const side = pick(rand, SIDES);
    const wick = round5(1.1 + rand() * 0.01);
    const buffer = pick(rand, [0, 0.00005, 0.0001, 0.0005]);
    const entry = round5(wick + (side === "buy" ? 1 : -1) * rand() * 0.002);
    const max = pick(rand, [undefined, 0.0003, 0.001, 0.005]);
    return { side, wick, buffer, entry, max, stop: computeStopLoss(side, wick, buffer, entry, max) };
  });
}

function gateVectors() {
  const out: Array<Record<string, unknown>> = [];
  for (let i = 0; i < 140; i += 1) {
    const rand = mulberry32(15000 + i);
    const stop = pick(rand, [0.0005, 0.001, 0.0015, 0.003, 0.5, 1.2]);
    const side = pick(rand, SIDES);
    const entry = 1.1;
    const input = {
      entryPrice: entry, stopDistance: stop, targetPrice: round5(entry + (side === "buy" ? 1 : -1) * stop * (1 + rand() * 6)), side,
      spread: pick(rand, [0, 0.00008, 0.0001, 0.0003, 0.1]), commission: pick(rand, [0, 0.00002, 0.00007]),
      costThreshold: pick(rand, [0.1, 0.25, 0.25, 0.5]), minRiskReward: pick(rand, [2, 3, 3, 4.5]),
    };
    out.push({ input, result: evaluateViabilityGates(input) });
  }
  // boundaries: cost exactly at the threshold, R:R exactly at the minimum, and degenerate distances
  const edge = [
    { entryPrice: 1, stopDistance: 4, targetPrice: 13, side: "buy", spread: 1, commission: 0, costThreshold: 0.25, minRiskReward: 2 },
    { entryPrice: 1, stopDistance: 1, targetPrice: 4, side: "buy", spread: 0, commission: 0, costThreshold: 0.25, minRiskReward: 3 },
    { entryPrice: 1, stopDistance: 0, targetPrice: 4, side: "buy", spread: 0.1, commission: 0, costThreshold: 0.25, minRiskReward: 3 },
    { entryPrice: 1, stopDistance: 0, targetPrice: 4, side: "buy", spread: 0, commission: 0, costThreshold: 0.25, minRiskReward: 3 },
    { entryPrice: 1, stopDistance: 0.0625, targetPrice: 2, side: "buy", spread: 0.015625, commission: 0, costThreshold: 0.2, minRiskReward: 0.0625 },
    { entryPrice: 1, stopDistance: 8, targetPrice: 40, side: "sell", spread: 0.5, commission: 0.5, costThreshold: 0.125, minRiskReward: 2.5 },
  ];
  for (const input of edge) out.push({ input, result: evaluateViabilityGates(input as never) });
  return out;
}

function preconditionVectors() {
  const stamps: string[] = [];
  const windows: Array<[string, string]> = [
    ["2026-01-05T00:00:00.000Z", "2026-01-07T00:00:00.000Z"], // winter, NY = UTC-5
    ["2026-03-07T00:00:00.000Z", "2026-03-10T12:00:00.000Z"], // DST starts Sunday 2026-03-08
    ["2026-07-06T00:00:00.000Z", "2026-07-08T00:00:00.000Z"], // summer, NY = UTC-4
    ["2026-10-30T00:00:00.000Z", "2026-11-03T12:00:00.000Z"], // DST ends Sunday 2026-11-01
  ];
  for (const [from, to] of windows) {
    for (let t = Date.parse(from); t < Date.parse(to); t += 15 * 60_000) stamps.push(new Date(t).toISOString());
  }
  return { stamps, killzone: stamps.map(isInKillzone), pastLunch: stamps.map(isPastNyLunch) };
}

function agreementVectors() {
  return Array.from({ length: 70 }, (_, i) => {
    const rand = mulberry32(16000 + i);
    const t0 = Date.parse("2026-01-05T08:00:00.000Z");
    const minutes = (m: number) => new Date(t0 + Math.round(m * 60_000)).toISOString();
    const proposals = Array.from({ length: Math.floor(rand() * 6) }, () => ({
      symbol: pick(rand, ["EURUSD", "GBPUSD"]), side: pick(rand, SIDES), detectedAt: minutes(Math.floor(rand() * 40)),
    }));
    const trades = Array.from({ length: Math.floor(rand() * 6) }, (_, k) => ({
      brokerPositionId: `P${i}-${k}`, symbol: pick(rand, ["EURUSD", "GBPUSD"]), side: pick(rand, SIDES), openedAt: minutes(Math.floor(rand() * 40)),
    }));
    const tolerance = pick(rand, [1, 3, 5, 10]);
    return { proposals, trades, tolerance, rows: reconcile(proposals, trades, tolerance) };
  });
}

// ---------------------------------------------------------------------------------------------------- write

const scenarios: Array<{ name: string; input: SetupProposalInput }> = [];
for (const [name, fault] of faults) {
  scenarios.push({ name: `buy/${name}`, input: fault(baseInput()) });
  scenarios.push({ name: `sell/${name}`, input: mirrored(fault(baseInput())) });
}
scenarios.push({ name: "buy/no-swing-to-break", input: asiaDrift() });
scenarios.push({ name: "sell/no-swing-to-break", input: mirrored(asiaDrift()) });
for (let seed = 1; seed <= 110; seed += 1) scenarios.push(perturbed(seed));
for (let seed = 1; seed <= 24; seed += 1) scenarios.push(randomScenario(seed));

const evaluated = scenarios.map(({ name, input }) => ({ name, input: packInput(input), outcome: evaluateSetup(input) }));
const stages: Record<string, number> = {};
for (const e of evaluated) {
  const key = e.outcome.status === "proposed" ? "proposed" : e.outcome.stage;
  stages[key] = (stages[key] ?? 0) + 1;
}
console.log("stage distribution:", JSON.stringify(stages));

writeFileSync(
  join(__dirname, "s01.json"),
  JSON.stringify({
    scenarios: evaluated,
    bias: biasVectors(),
    dealingRange: dealingRangeVectors(),
    liquidity: liquidityVectors(),
    sweep: sweepVectors(),
    displacement: displacementVectors(),
    poi: poiVectors(),
    stop: stopVectors(),
    gates: gateVectors(),
    preconditions: preconditionVectors(),
    agreement: agreementVectors(),
  }),
);
console.log(`s01.json written: ${evaluated.length} end-to-end scenarios`);
