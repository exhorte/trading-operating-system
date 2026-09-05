import { describe, expect, it } from "vitest";
import { scoreContext } from "./scoring";
import { DEFAULT_ANALYSIS_CONFIG } from "./config";
import type { AnalysisFeatures } from "./types";
import type { FairValueGap, StructureShift } from "@/lib/domain/analysis";

const weights = DEFAULT_ANALYSIS_CONFIG.scoreWeights;

const shift: StructureShift = {
  shiftId: "s1",
  symbol: "XAUUSD",
  timeframe: "M15",
  kind: "break_of_structure",
  direction: "bullish",
  brokenLevel: 100,
  occurredAt: "t",
};

const bullishFvg: FairValueGap = {
  fvgId: "f1",
  symbol: "XAUUSD",
  timeframe: "M15",
  direction: "bullish",
  high: 105,
  low: 100,
  filledPercent: 0,
  mitigatedAt: null,
  detectedAt: "t",
};

function features(overrides: Partial<AnalysisFeatures> = {}): AnalysisFeatures {
  return {
    swings: [],
    structureShifts: [shift],
    lastStructureShift: shift,
    liquidity: [],
    fairValueGaps: [bullishFvg],
    orderBlocks: [],
    session: "london",
    bias: "bullish",
    priceLocation: "discount",
    recentlySwept: true,
    ...overrides,
  };
}

describe("scoreContext", () => {
  it("awards full confluence when every component aligns", () => {
    const result = scoreContext({
      features: features(),
      currentPrice: 102, // inside the FVG
      sessionEnabled: true,
      weights,
    });
    expect(result.score).toBe(result.maxScore);
    expect(result.maxScore).toBe(10);
  });

  it("halves the PD-array score when an aligned array exists but price is outside it", () => {
    const result = scoreContext({
      features: features(),
      currentPrice: 130, // outside the FVG
      sessionEnabled: true,
      weights,
    });
    const pd = result.breakdown.find((c) => c.label === "PD arrays");
    expect(pd?.score).toBe(Math.round(weights.pdArray / 2));
  });

  it("scores zero for structure, sweep and PD arrays on an empty neutral context", () => {
    const result = scoreContext({
      features: features({
        bias: "neutral",
        lastStructureShift: null,
        recentlySwept: false,
        fairValueGaps: [],
        priceLocation: "equilibrium",
      }),
      currentPrice: 102,
      sessionEnabled: false,
      weights,
    });
    expect(result.score).toBe(0);
  });
});
