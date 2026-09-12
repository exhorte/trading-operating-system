import { describe, expect, it } from "vitest";
import { lastDealingRange, locationInRange } from "./dealing-range";
import { series } from "@/lib/analysis/test-helpers";

describe("lastDealingRange", () => {
  it("is null with fewer than two swings", () => {
    const candles = series([
      { high: 10, low: 9, close: 9.5 },
      { high: 10, low: 9, close: 9.5 },
      { high: 10, low: 9, close: 9.5 },
    ]);
    expect(lastDealingRange(candles, 1)).toBeNull();
  });

  it("takes the last swing and the nearest earlier opposite swing", () => {
    // swing low 8 at idx1, swing high 12 at idx3 (both confirmed with lookback 1).
    const candles = series([
      { high: 10, low: 9, close: 9.5 },
      { high: 9, low: 8, close: 8.5 }, // swing low 8
      { high: 10, low: 9, close: 9.5 },
      { high: 12, low: 10, close: 11 }, // swing high 12
      { high: 10, low: 9, close: 9.5 },
    ]);
    const range = lastDealingRange(candles, 1);
    expect(range).toEqual({ externalHigh: 12, externalLow: 8, equilibrium: 10 });
  });
});

describe("locationInRange", () => {
  const range = { externalHigh: 12, externalLow: 8, equilibrium: 10 };

  it("is discount strictly below equilibrium", () => {
    expect(locationInRange(9, range)).toBe("discount");
  });

  it("is premium strictly above equilibrium", () => {
    expect(locationInRange(11, range)).toBe("premium");
  });

  it("is equilibrium exactly at the midpoint — no neutral band either side", () => {
    expect(locationInRange(10, range)).toBe("equilibrium");
    expect(locationInRange(10.01, range)).toBe("premium");
    expect(locationInRange(9.99, range)).toBe("discount");
  });
});
