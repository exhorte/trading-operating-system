import { describe, expect, it } from "vitest";
import { detectStructureShifts, structuralBias } from "./structure";
import { detectSwings } from "./swings";
import { series } from "./test-helpers";

describe("detectStructureShifts", () => {
  // Swing high (12) at idx1 broken to the upside at idx3 -> BOS bullish.
  // Swing low (9) at idx5 broken to the downside at idx7 while bias is
  // bullish -> CHOCH bearish.
  const candles = series([
    { high: 10, low: 8, close: 9 }, // 0
    { high: 12, low: 9, close: 11 }, // 1 swing high 12
    { high: 11, low: 9, close: 10 }, // 2 confirms idx1
    { high: 13, low: 10, close: 12.5 }, // 3 close > 12 -> BOS bullish
    { high: 13, low: 11, close: 12 }, // 4
    { high: 12, low: 9, close: 10 }, // 5 swing low 9
    { high: 11, low: 10, close: 10.5 }, // 6 confirms idx5
    { high: 10, low: 7, close: 8 }, // 7 close < 9 -> CHOCH bearish
  ]);

  it("emits a bullish BOS then a bearish CHOCH", () => {
    const swings = detectSwings(candles, 1);
    const shifts = detectStructureShifts(candles, swings, 1);

    expect(shifts).toHaveLength(2);
    expect(shifts[0]).toMatchObject({
      kind: "break_of_structure",
      direction: "bullish",
      brokenLevel: 12,
    });
    expect(shifts[1]).toMatchObject({
      kind: "change_of_character",
      direction: "bearish",
      brokenLevel: 9,
    });
    expect(structuralBias(shifts)).toBe("bearish");
  });

  it("returns neutral bias when no structure breaks", () => {
    const flat = series([
      [10, 9],
      [10.2, 9.1],
      [10.1, 9.2],
      [10.2, 9.1],
    ]);
    const shifts = detectStructureShifts(flat, detectSwings(flat, 1), 1);
    expect(structuralBias(shifts)).toBe("neutral");
  });
});
