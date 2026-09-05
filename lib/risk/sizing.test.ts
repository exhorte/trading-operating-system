import { describe, expect, it } from "vitest";
import { evaluateSignalRisk } from "./sizing";
import { evaluateRiskState } from "./evaluate";
import { defaultRiskPolicy } from "./policy";
import type { RiskEvaluationInput } from "./types";

const policy = defaultRiskPolicy("acc-1");
const baseState: RiskEvaluationInput = {
  policy,
  initialBalance: 1000,
  dayStartEquity: 1000,
  equity: 1000,
  balance: 1000,
  positions: [],
  tradesToday: 0,
  consecutiveLosses: 0,
  spreadPoints: 20,
  session: "london",
  sessionTradingEnabled: true,
  now: "2026-01-05T10:00:00.000Z",
};

describe("evaluateSignalRisk", () => {
  it("sizes an approved trade to the risk-per-trade budget", () => {
    const state = evaluateRiskState(baseState);
    const decision = evaluateSignalRisk({
      signalId: "sig-1",
      accountId: "acc-1",
      entryPrice: 3300,
      stopLoss: 3290, // 10 stop distance
      balance: 1000,
      state,
      policy,
      now: "t",
    });
    // 1% of 1000 = 10 USD budget; 10 / (10 * 100) = 0.01 lot
    expect(decision.approved).toBe(true);
    expect(decision.approvedVolume).toBe(0.01);
  });

  it("rejects when the account is locked", () => {
    const locked = evaluateRiskState({ ...baseState, equity: 945 }); // >5% daily loss
    const decision = evaluateSignalRisk({
      signalId: "sig-2",
      accountId: "acc-1",
      entryPrice: 3300,
      stopLoss: 3290,
      balance: 945,
      state: locked,
      policy,
      now: "t",
    });
    expect(decision.approved).toBe(false);
    expect(decision.approvedVolume).toBeNull();
    expect(decision.reason).toContain("locked");
  });

  it("rejects when an entry gate blocks (closed session)", () => {
    const state = evaluateRiskState({
      ...baseState,
      session: "new_york_pm",
      sessionTradingEnabled: false,
    });
    const decision = evaluateSignalRisk({
      signalId: "sig-3",
      accountId: "acc-1",
      entryPrice: 3300,
      stopLoss: 3290,
      balance: 1000,
      state,
      policy,
      now: "t",
    });
    expect(decision.approved).toBe(false);
    expect(decision.reason).toContain("Session filter");
  });
});
