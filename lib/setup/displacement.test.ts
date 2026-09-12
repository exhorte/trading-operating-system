import { describe, expect, it } from "vitest";
import { detectDisplacement } from "./displacement";
import { series } from "@/lib/analysis/test-helpers";

const config = { atrPeriod: 14, minBodyAtrMultiple: 1.5, minFvgSize: 0.2 };
const oppositeSwingPrice = 103;

describe("detectDisplacement", () => {
  it("detects a valid bullish displacement: body break + big body + unfilled FVG", () => {
    const candles = series([
      { high: 101, low: 100, open: 100.5, close: 100.5 },
      { high: 102, low: 101, open: 101.5, close: 101.5 },
      { high: 103, low: 102, open: 102.5, close: 102.5 },
      // body close 110 > 103 (broken), body 7 >= 1.5*ATR, and forms a
      // bullish FVG with idx1 (high 102) < idx3 (low 102.8).
      { high: 110.2, low: 102.8, open: 103, close: 110 },
    ]);
    const result = detectDisplacement(candles, "buy", oppositeSwingPrice, config);
    expect(result).not.toBeNull();
    expect(result?.occurredAt).toBe(candles[3].openTime);
    expect(result?.fairValueGap.direction).toBe("bullish");
    expect(result?.fairValueGap.mitigatedAt).toBeNull();
  });

  it("rejects a wick-only break — body closes short of the swing, doesn't count", () => {
    const candles = series([
      { high: 101, low: 100, open: 100.5, close: 100.5 },
      { high: 102, low: 101, open: 101.5, close: 101.5 },
      { high: 103, low: 102, open: 102.5, close: 102.5 },
      // high 104 pierces 103, but the body closes at 102.8 — still below.
      { high: 104, low: 102.5, open: 102.5, close: 102.8 },
    ]);
    expect(detectDisplacement(candles, "buy", oppositeSwingPrice, config)).toBeNull();
  });

  it("rejects a body break too small relative to ATR", () => {
    const candles = series([
      { high: 101, low: 100, open: 100.5, close: 100.5 },
      { high: 102, low: 101, open: 101.5, close: 101.5 },
      { high: 103, low: 102, open: 102.5, close: 102.5 },
      // closes just past 103 but the body is tiny relative to recent ATR.
      { high: 103.3, low: 102.9, open: 103.0, close: 103.1 },
    ]);
    expect(detectDisplacement(candles, "buy", oppositeSwingPrice, config)).toBeNull();
  });
});
