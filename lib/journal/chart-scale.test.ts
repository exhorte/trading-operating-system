import { describe, expect, it } from "vitest";
import { computePriceScale, computeTimeScale } from "./chart-scale";

describe("computePriceScale", () => {
  it("maps the max price near the top (y≈0) and the min price near the bottom", () => {
    const scale = computePriceScale([{ high: 110, low: 90 }], 200);
    expect(scale.toY(110)).toBeLessThan(scale.toY(90));
    expect(scale.toY(110)).toBeGreaterThanOrEqual(0);
    expect(scale.toY(90)).toBeLessThanOrEqual(200);
  });

  it("pads beyond the tightest candle range so wicks are never clipped", () => {
    const scale = computePriceScale([{ high: 100, low: 100 }], 200);
    expect(scale.min).toBeLessThan(100);
    expect(scale.max).toBeGreaterThan(100);
  });

  it("widens the range to cover extra prices (levels/markers), not just candles", () => {
    const scale = computePriceScale([{ high: 100, low: 95 }], 200, [80, 120]);
    expect(scale.min).toBeLessThanOrEqual(80);
    expect(scale.max).toBeGreaterThanOrEqual(120);
  });

  it("is monotonic: a higher price always maps to a smaller (or equal) y", () => {
    const scale = computePriceScale([{ high: 4060, low: 4040 }], 300);
    expect(scale.toY(4055)).toBeLessThan(scale.toY(4045));
  });
});

describe("computeTimeScale", () => {
  it("spreads candles evenly across the width, centered in their slot", () => {
    const scale = computeTimeScale(4, 400);
    expect(scale.slotWidth).toBe(100);
    expect(scale.toX(0)).toBe(50);
    expect(scale.toX(3)).toBe(350);
  });

  it("never divides by zero for an empty candle set", () => {
    const scale = computeTimeScale(0, 400);
    expect(Number.isFinite(scale.slotWidth)).toBe(true);
    expect(Number.isFinite(scale.toX(0))).toBe(true);
  });
});
