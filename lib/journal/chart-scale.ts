/**
 * T05 — pure geometry for the candlestick capture chart. Kept separate from
 * the React component (components/journal/trade-chart.tsx) so the scale math
 * is unit-testable without rendering: given a price range/time range and a
 * pixel box, where does a given price or candle index land.
 */

export interface PriceScale {
  min: number;
  max: number;
  /** Price → SVG y (top = max price, per screen-space convention). */
  toY: (price: number) => number;
}

export interface TimeScale {
  count: number;
  /** Candle index → SVG x, centered in its slot. */
  toX: (index: number) => number;
  /** Width of one candle's slot (body/wick fit inside this). */
  slotWidth: number;
}

/**
 * A little headroom above/below the tightest price range so wicks and
 * horizontal level lines near the edge aren't clipped. `extraPrices` lets
 * callers fold in level/marker prices (entry, stop, TP, FVGs, …) so the
 * scale covers everything that will be drawn, not just the candle bodies.
 */
export function computePriceScale(
  candleHighsLows: Array<{ high: number; low: number }>,
  height: number,
  extraPrices: number[] = [],
  paddingRatio = 0.08,
): PriceScale {
  const highs = candleHighsLows.map((c) => c.high);
  const lows = candleHighsLows.map((c) => c.low);
  const allPrices = [...highs, ...lows, ...extraPrices];
  const rawMin = Math.min(...allPrices);
  const rawMax = Math.max(...allPrices);
  const span = rawMax - rawMin || 1;
  const padding = span * paddingRatio;
  const min = rawMin - padding;
  const max = rawMax + padding;
  const paddedSpan = max - min || 1;

  return {
    min,
    max,
    toY: (price: number) => height * (1 - (price - min) / paddedSpan),
  };
}

export function computeTimeScale(candleCount: number, width: number): TimeScale {
  const count = Math.max(candleCount, 1);
  const slotWidth = width / count;
  return {
    count,
    slotWidth,
    toX: (index: number) => index * slotWidth + slotWidth / 2,
  };
}
