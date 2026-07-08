import { describe, expect, it } from "vitest";
import { detectLiquidity } from "./liquidity";
import { detectSwings } from "./swings";
import { series } from "./test-helpers";

describe("detectLiquidity", () => {
  it("clusters near-equal swing highs and marks the pool swept when wicked", () => {
    const candles = series([
      [10, 8],
      [12, 9], // swing high 12.0
      [11, 9],
      [12.2, 9], // swing high 12.2 -> equal-highs pool with 12.0
      [11, 8],
      [13, 8], // wick above the pool -> swept
      [12, 8],
    ]);
    const swings = detectSwings(candles, 1);
    const levels = detectLiquidity(candles, swings, 0.3);

    const equalHighs = levels.find((l) => l.kind === "equal_highs");
    expect(equalHighs).toBeDefined();
    expect(equalHighs?.price).toBeCloseTo(12.1, 1);
    expect(equalHighs?.sweptAt).not.toBeNull();
  });

  it("derives previous-day high/low as today's liquidity targets", () => {
    // stepMinutes 200 spreads 10 candles across two UTC days.
    const candles = series(
      [
        [20, 18], // day 1
        [21, 17],
        [22, 16], // prev-day high 22 / low 16 live here
        [20, 19],
        [21, 18],
        [20, 17],
        [21, 18],
        [20, 19], // last day-1 candle
        [25, 24], // day 2
        [26, 23],
      ],
      { stepMinutes: 200 },
    );
    const levels = detectLiquidity(candles, detectSwings(candles, 1), 0.3);

    expect(levels.find((l) => l.kind === "previous_day_high")?.price).toBe(22);
    expect(levels.find((l) => l.kind === "previous_day_low")?.price).toBe(16);
  });
});
