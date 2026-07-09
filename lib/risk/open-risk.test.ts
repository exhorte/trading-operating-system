import { describe, expect, it } from "vitest";
import { openRiskPercent, positionRiskUsd } from "./open-risk";

describe("open risk", () => {
  it("prices one XAUUSD position's stop distance in USD", () => {
    // 10.00 stop distance * 0.1 lot * 100 = 100 USD
    expect(positionRiskUsd({ symbol: "XAUUSD", entryPrice: 3300, stopLoss: 3290, volume: 0.1 })).toBe(
      100,
    );
  });

  it("sums open risk as a percent of balance", () => {
    const positions = [
      { symbol: "XAUUSD", entryPrice: 3300, stopLoss: 3290, volume: 0.1 }, // 100 USD
      { symbol: "XAUUSD", entryPrice: 3310, stopLoss: 3305, volume: 0.2 }, // 100 USD
    ];
    // 200 USD on a 10_000 balance -> 2%
    expect(openRiskPercent(positions, 10_000)).toBe(2);
  });

  it("is zero on a non-positive balance", () => {
    expect(openRiskPercent([], 0)).toBe(0);
  });

  it("excludes positions with no stop-loss (undefined risk)", () => {
    expect(
      positionRiskUsd({ symbol: "XAUUSD", entryPrice: 4053, stopLoss: 0, volume: 0.1 }),
    ).toBe(0);
  });
});
