/**
 * Deterministic inputs shared by the golden-vector generators: a seeded PRNG and a candle random walk. Nothing here is a detector;
 * the vectors only mean something because the SAME inputs are fed to the TypeScript original (which writes them down with its
 * outputs) and then to the Python port (which reads them back).
 */

import type { Candle } from "@/lib/domain/market";
import type { Timeframe } from "@/lib/domain/primitives";

export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface WalkSpec {
  seed: number;
  n: number;
  start: string;
  stepMinutes: number;
  timeframe: Timeframe;
  symbol: string;
  startPrice: number;
  vol: number;
  digits: number;
  wave?: number;
  period?: number;
  lastClosed?: boolean;
}

export function walk(spec: WalkSpec): Candle[] {
  const rand = mulberry32(spec.seed);
  const scale = 10 ** spec.digits;
  const round = (x: number) => Math.round(x * scale) / scale;
  const t0 = Date.parse(spec.start);
  let previous = spec.startPrice;
  const out: Candle[] = [];
  for (let i = 0; i < spec.n; i += 1) {
    const slow = (spec.wave ?? 0) * Math.sin(i / (spec.period ?? 20)) * spec.vol;
    const drift = (rand() - 0.5) * 2 * spec.vol + slow;
    const open = round(previous);
    const close = round(previous + drift);
    const high = round(Math.max(open, close) + rand() * spec.vol * 0.7);
    const low = round(Math.min(open, close) - rand() * spec.vol * 0.7);
    out.push({
      symbol: spec.symbol,
      timeframe: spec.timeframe,
      openTime: new Date(t0 + i * spec.stepMinutes * 60_000).toISOString(),
      open,
      high,
      low,
      close,
      volume: Math.floor(rand() * 1000),
      closed: i < spec.n - 1 || (spec.lastClosed ?? true),
    });
    previous = close;
  }
  return out;
}
