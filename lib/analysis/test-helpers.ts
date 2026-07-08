/**
 * Deterministic candle builders for engine unit tests. Not shipped in the app
 * bundle (only imported by *.test.ts). Times increment by one timeframe step
 * from a fixed epoch so fixtures are stable and ordered.
 */

import type { Candle } from "@/lib/domain/market";
import type { SymbolCode, Timeframe } from "@/lib/domain/primitives";

const BASE_EPOCH = Date.UTC(2026, 0, 5, 0, 0, 0); // Mon 2026-01-05 00:00 UTC

/** One candle from high/low (+ optional open/close), spaced `stepMinutes` apart. */
export function candleAt(
  index: number,
  high: number,
  low: number,
  opts: Partial<Pick<Candle, "open" | "close" | "volume">> & {
    symbol?: SymbolCode;
    timeframe?: Timeframe;
    stepMinutes?: number;
  } = {},
): Candle {
  const step = opts.stepMinutes ?? 15;
  return {
    symbol: opts.symbol ?? "XAUUSD",
    timeframe: opts.timeframe ?? "M15",
    openTime: new Date(BASE_EPOCH + index * step * 60_000).toISOString(),
    open: opts.open ?? (high + low) / 2,
    high,
    low,
    close: opts.close ?? (high + low) / 2,
    volume: opts.volume ?? 100,
    closed: true,
  };
}

/** Build a series from [high, low] pairs, auto-indexed. */
export function series(
  bars: Array<[number, number] | { high: number; low: number; open?: number; close?: number }>,
  opts: { symbol?: SymbolCode; timeframe?: Timeframe; stepMinutes?: number } = {},
): Candle[] {
  return bars.map((bar, i) =>
    Array.isArray(bar)
      ? candleAt(i, bar[0], bar[1], opts)
      : candleAt(i, bar.high, bar.low, { ...opts, open: bar.open, close: bar.close }),
  );
}
