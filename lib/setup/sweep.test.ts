import { describe, expect, it } from "vitest";
import { detectSweep } from "./sweep";
import { series } from "@/lib/analysis/test-helpers";

const level = { kind: "previous_day_low" as const, price: 1.1 };

describe("detectSweep", () => {
  it("detects a buy-side sweep: low breaches the level, close reclaims it", () => {
    const candles = series([
      { high: 1.102, low: 1.101, close: 1.1015 }, // level not touched yet
      { high: 1.103, low: 1.098, close: 1.1012 }, // low < 1.10, close > 1.10 -> sweep
    ]);
    const sweep = detectSweep(candles, level, "buy");
    expect(sweep).toMatchObject({ level, side: "buy", wickExtreme: 1.098 });
    expect(sweep?.sweptAt).toBe(candles[1].openTime);
  });

  it("detects a sell-side sweep: high breaches the level, close reclaims it", () => {
    const highLevel = { kind: "previous_day_high" as const, price: 1.1 };
    const candles = series([
      { high: 1.099, low: 1.097, close: 1.098 },
      { high: 1.103, low: 1.098, close: 1.0985 }, // high > 1.10, close < 1.10 -> sweep
    ]);
    const sweep = detectSweep(candles, highLevel, "sell");
    expect(sweep).toMatchObject({ side: "sell", wickExtreme: 1.103 });
  });

  it("is a cassure, not a sweep, when the candle breaches without reclaiming — rejected, not deferred", () => {
    const candles = series([
      { high: 1.103, low: 1.098, close: 1.099 }, // low < 1.10 but close also < 1.10 -> no reclaim
      { high: 1.101, low: 1.0995, close: 1.1005 }, // this bar WOULD reclaim, but must not be reached
    ]);
    expect(detectSweep(candles, level, "buy")).toBeNull();
  });

  it("returns null when the level is never touched", () => {
    const candles = series([
      { high: 1.103, low: 1.101, close: 1.102 },
      { high: 1.104, low: 1.1015, close: 1.103 },
    ]);
    expect(detectSweep(candles, level, "buy")).toBeNull();
  });
});
