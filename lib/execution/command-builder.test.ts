import { describe, expect, it } from "vitest";
import { buildPlaceOrderCommand } from "./command-builder";
import type { MarketContextState } from "@/lib/domain/analysis";
import type { RiskDecision } from "@/lib/domain/risk";
import type { StrategySignal } from "@/lib/domain/strategy";

const context: MarketContextState = {
  symbol: "XAUUSDm",
  timeframe: "M15",
  bias: "bullish",
  session: "london",
  lastStructureShift: null,
  activeLiquidityLevels: [],
  activeFairValueGaps: [],
  activeOrderBlocks: [],
  score: 6,
  maxScore: 10,
  scoreBreakdown: [],
  computedAt: "t",
};

const signal: StrategySignal = {
  signalId: "sig-101",
  strategyId: "ict-silver-bullet-v1",
  accountId: "436634705",
  symbol: "XAUUSDm",
  side: "buy",
  status: "approved",
  entryPrice: 4053,
  stopLoss: 4048,
  takeProfit: 4063,
  score: 6,
  maxScore: 10,
  marketContext: context,
  riskApprovalId: null,
  createdAt: "2026-07-11T10:00:00.000Z",
  expiresAt: "2026-07-11T10:05:00.000Z",
};

const approved: RiskDecision = {
  approvalId: "risk-sig-101",
  signalId: "sig-101",
  accountId: "436634705",
  approved: true,
  approvedVolume: 0.02,
  gates: [],
  reason: "Approved: 0.02 lot at 1% risk",
  decidedAt: "t",
};

describe("buildPlaceOrderCommand", () => {
  it("builds a market order sized by the RISK-approved volume, linked to the approval", () => {
    const cmd = buildPlaceOrderCommand({
      signal,
      decision: approved,
      agentId: "mt5-observer-1",
      now: "2026-07-11T10:00:10.000Z",
    });
    expect(cmd).not.toBeNull();
    expect(cmd).toMatchObject({
      kind: "place_order",
      commandId: "cmd-sig-101",
      protocolVersion: 1,
      riskApprovalId: "risk-sig-101",
      volume: 0.02, // decision volume, never the strategy's ask
      orderType: "market",
      side: "buy",
      stopLoss: 4048,
      takeProfit: 4063,
      signalId: "sig-101",
    });
    // expiry = issuedAt + TTL, in the future
    expect(Date.parse(cmd!.expiresAt)).toBeGreaterThan(Date.parse(cmd!.issuedAt));
  });

  it("returns null for a rejected decision (no command, ever)", () => {
    const cmd = buildPlaceOrderCommand({
      signal,
      decision: { ...approved, approved: false, approvedVolume: null, reason: "Rejected" },
      agentId: "mt5-observer-1",
      now: "t",
    });
    expect(cmd).toBeNull();
  });

  it("returns null when the decision is unsized or for another signal", () => {
    expect(
      buildPlaceOrderCommand({
        signal,
        decision: { ...approved, approvedVolume: 0 },
        agentId: "a",
        now: "t",
      }),
    ).toBeNull();
    expect(
      buildPlaceOrderCommand({
        signal,
        decision: { ...approved, signalId: "sig-999" },
        agentId: "a",
        now: "t",
      }),
    ).toBeNull();
  });
});
