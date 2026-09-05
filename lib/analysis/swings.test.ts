import { describe, expect, it } from "vitest";
import { detectSwings } from "./swings";
import { series } from "./test-helpers";

describe("detectSwings", () => {
  it("finds a strict swing high and swing low with lookback 1", () => {
    // index:   0        1        2        3        4
    // a low at index 2, a high at index... build a clear V then peak.
    const candles = series([
      [10, 8], // 0
      [11, 9], // 1  higher than 0 and 2 highs -> swing high
      [9, 5], // 2   lower than 1 and 3 lows  -> swing low
      [12, 7], // 3
      [10, 8], // 4
    ]);

    const swings = detectSwings(candles, 1);

    expect(swings).toContainEqual(expect.objectContaining({ kind: "high", index: 1, price: 11 }));
    expect(swings).toContainEqual(expect.objectContaining({ kind: "low", index: 2, price: 5 }));
  });

  it("never reports a pivot inside the trailing lookback window (no look-ahead)", () => {
    const candles = series([
      [10, 8],
      [11, 9],
      [12, 7], // would be a high, but is within lookback of the array end
      [11, 9],
    ]);

    const swings = detectSwings(candles, 2);
    // With 4 candles and lookback 2, no interior index qualifies.
    expect(swings).toEqual([]);
  });

  it("requires strict inequality: a flat top is not a swing high", () => {
    const candles = series([
      [10, 8],
      [12, 9],
      [12, 9], // equal high to neighbour -> not strict
      [11, 8],
    ]);

    const highs = detectSwings(candles, 1).filter((s) => s.kind === "high");
    expect(highs).toEqual([]);
  });
});
