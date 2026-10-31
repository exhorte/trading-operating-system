import { describe, expect, it } from "vitest";
import type { MarketContextState } from "@/lib/api/generated";
import { toMarketContextView } from "./market-context-view";

const state: MarketContextState = {
  symbol: "XAUUSD",
  timeframe: "M15",
  bias: "bullish",
  session: "new_york_am",
  lastStructureShift: {
    shiftId: "s1",
    symbol: "XAUUSD",
    timeframe: "M15",
    kind: "break_of_structure",
    direction: "bullish",
    brokenLevel: 3305.2,
    occurredAt: "2026-01-05T13:00:00.000Z",
  },
  activeLiquidityLevels: [
    {
      levelId: "l1",
      symbol: "XAUUSD",
      timeframe: "M15",
      kind: "previous_day_high",
      price: 3318.5,
      sweptAt: null,
      detectedAt: "2026-01-05T00:00:00.000Z",
    },
  ],
  activeFairValueGaps: [
    {
      fvgId: "f1",
      symbol: "XAUUSD",
      timeframe: "M15",
      direction: "bullish",
      high: 3309.1,
      low: 3306.8,
      filledPercent: 0,
      mitigatedAt: null,
      detectedAt: "2026-01-05T12:45:00.000Z",
    },
  ],
  activeOrderBlocks: [],
  score: 7,
  maxScore: 10,
  scoreBreakdown: [{ label: "Structure", score: 3, maxScore: 3 }],
  computedAt: "2026-01-05T13:30:00.000Z",
};

describe("toMarketContextView", () => {
  it("puts the structured context into panel-ready strings", () => {
    const view = toMarketContextView(state);
    expect(view.bias).toBe("bullish");
    expect(view.structureState).toBe("Uptrend after BOS");
    expect(view.lastStructureEvent).toBe("BOS above 3,305.2 (M15)");
    expect(view.liquidityNote).toContain("PDH 3,318.5");
    expect(view.pdArrayNote).toContain("bullish FVG");
    expect(view.score).toBe(7);
    expect(view.updatedAt).toBe(state.computedAt);
  });

  it("uses honest fallbacks when nothing is detected", () => {
    const view = toMarketContextView({
      ...state,
      bias: "neutral",
      lastStructureShift: null,
      activeLiquidityLevels: [],
      activeFairValueGaps: [],
    });
    expect(view.structureState).toBe("Ranging");
    expect(view.lastStructureEvent).toBe("No confirmed shift");
    expect(view.liquidityNote).toBe("No tracked pools");
    expect(view.pdArrayNote).toBe("No active PD arrays");
  });

  it("names a change of character and a bearish break", () => {
    const view = toMarketContextView({
      ...state,
      bias: "bearish",
      lastStructureShift: { ...state.lastStructureShift!, kind: "change_of_character", direction: "bearish" },
      activeOrderBlocks: [
        { orderBlockId: "o1", symbol: "XAUUSD", timeframe: "M15", direction: "bearish", high: 3320, low: 3318, mitigatedAt: null, detectedAt: "x" },
      ],
    });
    expect(view.structureState).toBe("Downtrend after CHOCH");
    expect(view.lastStructureEvent).toBe("CHOCH below 3,305.2 (M15)");
    expect(view.pdArrayNote).toBe("bullish FVG 3,306.8-3,309.1; bearish OB 3,318-3,320");
  });

  it("lists at most the first three pools", () => {
    const level = state.activeLiquidityLevels[0];
    const view = toMarketContextView({ ...state, activeLiquidityLevels: [1, 2, 3, 4].map((i) => ({ ...level, levelId: `l${i}`, price: 3300 + i })) });
    expect(view.liquidityNote.split(", ")).toHaveLength(3);
  });
});
