import { describe, expect, it } from "vitest";
import { toRiskDecisionView, toStrategySignalReadModel } from "./projections";
import type { MarketContextState } from "@/lib/domain/analysis";
import type { StrategySignal } from "@/lib/domain/strategy";
import type { RiskDecision } from "@/lib/domain/risk";

const context: MarketContextState = {
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
    brokenLevel: 3305,
    occurredAt: "t",
  },
  activeLiquidityLevels: [],
  activeFairValueGaps: [],
  activeOrderBlocks: [],
  score: 7,
  maxScore: 10,
  scoreBreakdown: [],
  computedAt: "2026-01-05T13:30:00.000Z",
};

const signal: StrategySignal = {
  signalId: "sig-016",
  strategyId: "ict-silver-bullet-v1",
  accountId: "acc-1",
  symbol: "XAUUSD",
  side: "buy",
  status: "risk_review",
  entryPrice: 3312,
  stopLoss: 3307,
  takeProfit: 3322,
  score: 7,
  maxScore: 10,
  marketContext: context,
  riskApprovalId: null,
  createdAt: "2026-01-05T13:31:00.000Z",
  expiresAt: "2026-01-05T13:36:00.000Z",
};

const decision: RiskDecision = {
  approvalId: "risk-sig-016",
  signalId: "sig-016",
  accountId: "acc-1",
  approved: true,
  approvedVolume: 0.02,
  gates: [],
  reason: "Approved: 0.02 lot at 1% risk",
  decidedAt: "2026-01-05T13:31:05.000Z",
};

describe("toStrategySignalReadModel", () => {
  it("summarises the frozen context and leaves riskDecision null before review", () => {
    const rm = toStrategySignalReadModel(signal);
    expect(rm.signalId).toBe("sig-016");
    expect(rm.contextSummary).toBe("bullish bias · BOS · new_york_am");
    expect(rm.riskDecision).toBeNull();
    expect(rm.score).toBe(7);
  });

  it("carries the decision reason once reviewed", () => {
    const rm = toStrategySignalReadModel({ ...signal, status: "approved" }, decision);
    expect(rm.status).toBe("approved");
    expect(rm.riskDecision).toBe("Approved: 0.02 lot at 1% risk");
  });
});

describe("toRiskDecisionView", () => {
  it("flattens a domain RiskDecision to the audit-grade view", () => {
    const view = toRiskDecisionView(decision);
    expect(view).toMatchObject({
      approvalId: "risk-sig-016",
      signalId: "sig-016",
      approved: true,
      approvedVolume: 0.02,
      reason: "Approved: 0.02 lot at 1% risk",
    });
  });
});
