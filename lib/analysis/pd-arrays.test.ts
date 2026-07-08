import { describe, expect, it } from "vitest";
import { detectFairValueGaps, detectOrderBlocks } from "./pd-arrays";
import { detectStructureShifts } from "./structure";
import { detectSwings } from "./swings";
import { series } from "./test-helpers";

describe("detectFairValueGaps", () => {
  it("detects a bullish 3-candle imbalance", () => {
    const candles = series([
      [10, 9],
      [12, 11],
      [14, 13], // candle[0].high 10 < candle[2].low 13 -> bullish gap 10..13
    ]);
    const gaps = detectFairValueGaps(candles, 0.2);
    expect(gaps).toHaveLength(1);
    expect(gaps[0]).toMatchObject({ direction: "bullish", low: 10, high: 13, mitigatedAt: null });
    expect(gaps[0].filledPercent).toBe(0);
  });

  it("detects a bearish gap and marks it mitigated once price trades through", () => {
    const candles = series([
      [14, 13],
      [12, 11],
      [10, 9], // candle[2].high 10 < candle[0].low 13 -> bearish gap 10..13
      [14, 12.5], // rallies back up through the gap
    ]);
    const gaps = detectFairValueGaps(candles, 0.2);
    const bearish = gaps.find((g) => g.direction === "bearish");
    expect(bearish).toMatchObject({ low: 10, high: 13 });
    expect(bearish?.filledPercent).toBe(100);
    expect(bearish?.mitigatedAt).not.toBeNull();
  });

  it("ignores gaps smaller than minSize", () => {
    const candles = series([
      [10, 9],
      [11, 10],
      [11.1, 10.05], // tiny gap 10..10.05
    ]);
    expect(detectFairValueGaps(candles, 0.2)).toEqual([]);
  });
});

describe("detectOrderBlocks", () => {
  it("takes the last down-candle before a bullish BOS as a bullish OB", () => {
    const candles = series([
      { high: 10, low: 8, open: 9.5, close: 8.5 },
      { high: 11, low: 9, open: 9, close: 10.5 }, // swing high 11
      { high: 10.5, low: 9, open: 10, close: 9.5 }, // down candle, confirms idx1
      { high: 13, low: 10, open: 10.2, close: 12.5 }, // close > 11 -> BOS bullish
      { high: 11, low: 9.5, open: 10.5, close: 10 }, // returns into OB -> mitigation
    ]);
    const swings = detectSwings(candles, 1);
    const shifts = detectStructureShifts(candles, swings, 1);
    const blocks = detectOrderBlocks(candles, shifts);

    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ direction: "bullish", high: 10.5, low: 9 });
    expect(blocks[0].mitigatedAt).not.toBeNull();
  });
});
