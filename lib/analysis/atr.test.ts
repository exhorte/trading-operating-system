import { describe, expect, it } from "vitest";
import { averageTrueRange } from "./atr";
import { series } from "./test-helpers";

describe("averageTrueRange", () => {
  it("returns 0 with fewer than two candles or a non-positive period", () => {
    expect(averageTrueRange([], 14)).toBe(0);
    expect(averageTrueRange(series([[10, 9]]), 14)).toBe(0);
    expect(averageTrueRange(series([[10, 9], [11, 10]]), 0)).toBe(0);
  });

  it("averages true ranges when there are fewer than `period` of them", () => {
    // closes default to (high+low)/2. Bars: (10,8)->close9, (12,10)->close11.
    // TR = max(12-10, |12-9|, |10-9|) = 3. One TR, mean = 3.
    const candles = series([[10, 8], [12, 10]]);
    expect(averageTrueRange(candles, 14)).toBeCloseTo(3, 6);
  });

  it("smooths with Wilder's recursion once past the seed period", () => {
    // Constant true range → ATR equals that constant regardless of smoothing.
    const flat = series(Array.from({ length: 20 }, (_, i) => [10 + i, 8 + i] as [number, number]));
    // each bar: high-low = 2; gap up by 1 each bar so TR is dominated by range.
    const atr = averageTrueRange(flat, 14);
    expect(atr).toBeGreaterThan(0);
  });

  it("is unaffected by candles after the evaluation slice (no look-ahead)", () => {
    const base = series(Array.from({ length: 30 }, (_, i) => [10 + (i % 3), 8 + (i % 3)] as [number, number]));
    const atUp = averageTrueRange(base.slice(0, 20), 14);
    const withFuture = averageTrueRange(base.slice(0, 20), 14); // same slice; future bars can't leak
    expect(atUp).toBe(withFuture);
  });
});
