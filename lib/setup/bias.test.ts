import { describe, expect, it } from "vitest";
import { dailyBias } from "./bias";
import { series } from "@/lib/analysis/test-helpers";

// Same bullish BOS shape on both timeframes: swing high 12 broken at idx3.
const bullishShift = series([
  { high: 10, low: 8, close: 9 },
  { high: 12, low: 9, close: 11 }, // swing high 12
  { high: 11, low: 9, close: 10 }, // confirms idx1
  { high: 13, low: 10, close: 12.5 }, // close > 12 -> BOS bullish
]);

// Same bearish BOS shape: swing low 8 broken at idx3.
const bearishShift = series([
  { high: 12, low: 10, close: 11 },
  { high: 11, low: 8, close: 9 }, // swing low 8
  { high: 11, low: 9, close: 10 }, // confirms idx1
  { high: 10, low: 7, close: 7.5 }, // close < 8 -> BOS bearish
]);

// No confirmed shift at all.
const flat = series([
  { high: 10, low: 9, close: 9.5 },
  { high: 10, low: 9, close: 9.5 },
  { high: 10, low: 9, close: 9.5 },
  { high: 10, low: 9, close: 9.5 },
]);

describe("dailyBias", () => {
  it("is bullish when H4 and D1 agree", () => {
    expect(dailyBias(bullishShift, bullishShift, 1)).toBe("bullish");
  });

  it("is neutral when H4 and D1 disagree", () => {
    expect(dailyBias(bullishShift, bearishShift, 1)).toBe("neutral");
  });

  it("is neutral when either timeframe has no confirmed structure", () => {
    expect(dailyBias(bullishShift, flat, 1)).toBe("neutral");
    expect(dailyBias(flat, flat, 1)).toBe("neutral");
  });
});
