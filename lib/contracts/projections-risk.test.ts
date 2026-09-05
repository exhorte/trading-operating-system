import { describe, expect, it } from "vitest";
import { toRiskStatusReadModel } from "./projections";
import { evaluateRiskState } from "@/lib/risk";
import { defaultRiskPolicy } from "@/lib/risk";

describe("toRiskStatusReadModel", () => {
  const policy = defaultRiskPolicy("acc-1");

  it("merges policy limits with evaluated usage and mode", () => {
    const state = evaluateRiskState({
      policy,
      initialBalance: 1000,
      dayStartEquity: 1000,
      equity: 965, // 3.5% daily loss -> warning
      balance: 965,
      positions: [],
      tradesToday: 2,
      consecutiveLosses: 1,
      spreadPoints: 20,
      session: "london",
      sessionTradingEnabled: true,
      upcomingReleases: [],
      now: "t",
    });
    const rm = toRiskStatusReadModel(state, policy);
    expect(rm.state).toBe("warning");
    expect(rm.dailyLossLimitPercent).toBe(5);
    expect(rm.dailyLossUsedPercent).toBe(3.5);
    expect(rm.maxTradesPerDay).toBe(6);
    expect(rm.tradesToday).toBe(2);
    expect(rm.gates.length).toBeGreaterThan(0);
  });

  it("passes through null trade counts for honest n/a", () => {
    const state = evaluateRiskState({
      policy,
      initialBalance: 1000,
      dayStartEquity: 1000,
      equity: 1000,
      balance: 1000,
      positions: [],
      tradesToday: null,
      consecutiveLosses: null,
      spreadPoints: null,
      session: "off_session",
      sessionTradingEnabled: false,
      upcomingReleases: [],
      now: "t",
    });
    const rm = toRiskStatusReadModel(state, policy);
    expect(rm.tradesToday).toBeNull();
    expect(rm.consecutiveLosses).toBeNull();
  });
});
