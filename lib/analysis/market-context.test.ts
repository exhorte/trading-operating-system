import { describe, expect, it } from "vitest";
import { analyzeMarketContext } from "./market-context";
import { DEFAULT_ANALYSIS_CONFIG } from "./config";
import { series } from "./test-helpers";

const cfg = { ...DEFAULT_ANALYSIS_CONFIG, swingLookback: 1 };

describe("analyzeMarketContext", () => {
  it("assembles a coherent bullish context (BOS + unmitigated FVG)", () => {
    // downswing + sweep, then upside displacement that breaks structure and
    // leaves a bullish fair value gap behind.
    const candles = series([
      { high: 100, low: 98, open: 99.5, close: 98.2 }, // 0
      { high: 101, low: 99, open: 99, close: 100.5 }, // 1 swing high 101
      { high: 100.5, low: 98.5, open: 100, close: 98.8 }, // 2
      { high: 100, low: 97, open: 98.5, close: 97.2 }, // 3 swing low 97
      { high: 99, low: 98, open: 97.5, close: 98.9 }, // 4
      { high: 103, low: 101.5, open: 99, close: 102.8 }, // 5 close > 101 -> BOS; gap 100..101.5
      { high: 103.5, low: 102, open: 102.9, close: 103.2 }, // 6
    ]);

    const state = analyzeMarketContext({
      symbol: "XAUUSD",
      timeframe: "M15",
      candles,
      config: cfg,
    });

    expect(state.bias).toBe("bullish");
    expect(state.lastStructureShift?.kind).toBe("break_of_structure");
    expect(state.lastStructureShift?.direction).toBe("bullish");
    expect(state.maxScore).toBe(10);
    expect(state.score).toBeGreaterThan(0);
    expect(state.activeFairValueGaps.some((g) => g.direction === "bullish")).toBe(true);
    // computed at the last closed candle, never past it (no look-ahead).
    expect(state.computedAt).toBe(candles[candles.length - 1].openTime);
    // breakdown sums to the reported score.
    expect(state.scoreBreakdown.reduce((s, c) => s + c.score, 0)).toBe(state.score);
  });

  it("returns a neutral empty state for no candles", () => {
    const state = analyzeMarketContext({ symbol: "XAUUSD", timeframe: "M15", candles: [] });
    expect(state.bias).toBe("neutral");
    expect(state.score).toBe(0);
    expect(state.maxScore).toBe(10);
    expect(state.activeFairValueGaps).toEqual([]);
  });
});
