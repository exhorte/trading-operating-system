/**
 * Deterministic synthetic XAUUSD M15 candle series used to feed the analysis
 * engine in the mock cockpit. The shape (uptrend with a mid pullback) reliably
 * produces real structure/PD-array detections — but it is synthetic data, not a
 * market feed, so the MOCK badge stays on. `nextCandles` advances the window so
 * the computed context updates live.
 */

import type { Candle } from "@/lib/domain/market";

const SYMBOL = "XAUUSD";
const TIMEFRAME = "M15";
const STEP_MS = 15 * 60_000;
const COUNT = 64;

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/** A seeded generator so the snapshot is identical on every connect/resync. */
export function mockCandles(count: number = COUNT): Candle[] {
  const start = Date.now() - count * STEP_MS;
  let seed = 2026_07_05;
  const rand = () => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
  };

  const candles: Candle[] = [];
  for (let i = 0; i < count; i += 1) {
    const t = i / (count - 1);
    // Overall +30 drift with a pullback between t≈0.35 and t≈0.55.
    const trend = 30 * t;
    const dip = t > 0.35 && t < 0.55 ? -12 * Math.sin(((t - 0.35) / 0.2) * Math.PI) : 0;
    const mid = 3300 + trend + dip + (rand() - 0.5) * 1.2;
    const open = mid + (rand() - 0.5) * 0.6;
    const close = mid + (rand() - 0.5) * 0.6;
    candles.push({
      symbol: SYMBOL,
      timeframe: TIMEFRAME,
      openTime: new Date(start + i * STEP_MS).toISOString(),
      open: round2(open),
      high: round2(Math.max(open, close) + rand() * 0.9),
      low: round2(Math.min(open, close) - rand() * 0.9),
      close: round2(close),
      volume: 80 + Math.round(rand() * 120),
      closed: true,
    });
  }
  return candles;
}

/** Drop the oldest candle and append a fresh one continuing the walk. */
export function nextCandles(prev: Candle[]): Candle[] {
  const last = prev[prev.length - 1];
  const open = last.close;
  const close = round2(open + (Math.random() - 0.48) * 2.2); // slight upward bias
  const candle: Candle = {
    symbol: SYMBOL,
    timeframe: TIMEFRAME,
    openTime: new Date(Date.parse(last.openTime) + STEP_MS).toISOString(),
    open,
    high: round2(Math.max(open, close) + Math.random() * 0.9),
    low: round2(Math.min(open, close) - Math.random() * 0.9),
    close,
    volume: 80 + Math.round(Math.random() * 120),
    closed: true,
  };
  return [...prev.slice(1), candle];
}
