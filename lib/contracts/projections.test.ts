import { describe, expect, it } from "vitest";
import { toMarketContextReadModel } from "./projections";
import type { MarketContextState } from "@/lib/domain/analysis";

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

describe("toMarketContextReadModel", () => {
  it("humanises the structured context into panel-ready strings", () => {
    const rm = toMarketContextReadModel(state);
    expect(rm.bias).toBe("bullish");
    expect(rm.structureState).toBe("Uptrend after BOS");
    expect(rm.lastStructureEvent).toBe("BOS above 3,305.2 (M15)");
    expect(rm.liquidityNote).toContain("PDH 3,318.5");
    expect(rm.pdArrayNote).toContain("bullish FVG");
    expect(rm.score).toBe(7);
    expect(rm.updatedAt).toBe(state.computedAt);
  });

  it("uses honest fallbacks when nothing is detected", () => {
    const rm = toMarketContextReadModel({
      ...state,
      bias: "neutral",
      lastStructureShift: null,
      activeLiquidityLevels: [],
      activeFairValueGaps: [],
    });
    expect(rm.structureState).toBe("Ranging");
    expect(rm.lastStructureEvent).toBe("No confirmed shift");
    expect(rm.liquidityNote).toBe("No tracked pools");
    expect(rm.pdArrayNote).toBe("No active PD arrays");
  });
});
