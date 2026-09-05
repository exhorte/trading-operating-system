import { describe, expect, it } from "vitest";
import { computeSizingPanel } from "./sizing-panel";
import type { AccountSummary, RiskStatus } from "@/lib/contracts/snapshots";

const account: AccountSummary = {
  accountId: "acc-1",
  label: "Test account",
  broker: "Test-Demo",
  currency: "USD",
  balance: 1000,
  equity: 1000,
  dailyPnl: 0,
  dailyDrawdownPercent: 0,
  totalDrawdownPercent: 0,
  openRiskPercent: 0,
};

const normalRisk: RiskStatus = {
  state: "normal",
  dailyLossLimitPercent: 5,
  dailyLossUsedPercent: 0,
  maxDrawdownLimitPercent: 10,
  maxDrawdownUsedPercent: 0,
  maxTradesPerDay: 6,
  tradesToday: 0,
  consecutiveLosses: 0,
  lockoutReason: null,
  lockoutUntil: null,
  gates: [
    { gateId: "gate-spread", label: "Spread gate", state: "open", detail: "20 pts < 40 pts limit" },
  ],
};

describe("computeSizingPanel", () => {
  it("sizes an approved trade and reports no floor distortion", () => {
    const result = computeSizingPanel({
      entryPrice: 3300,
      stopLoss: 3290, // 10 distance, matches lib/risk/sizing.test.ts
      takeProfit: null,
      account,
      risk: normalRisk,
      now: "2026-01-05T10:00:00.000Z",
    });

    expect(result.stopDistance).toBe(10);
    expect(result.stopDistancePoints).toBe(1000); // 1 point = 0.01
    expect(result.stopDistancePips).toBe(100); // 1 pip = 10 points
    expect(result.decision?.approved).toBe(true);
    expect(result.decision?.approvedVolume).toBe(0.01);
    expect(result.targetRiskUsd).toBeCloseTo(10); // 1% of 1000
    expect(result.realRiskUsd).toBeCloseTo(10);
    expect(result.floorApplied).toBe(false);
    expect(result.dailyBudgetConsumedPercent).toBeCloseTo(20); // 10 / (5% of 1000 = 50)
  });

  it("flags the 0.01-lot floor when it pushes real risk above the target", () => {
    const smallAccount: AccountSummary = { ...account, balance: 100, equity: 100 };
    const result = computeSizingPanel({
      entryPrice: 3300,
      stopLoss: 3290, // same 10 distance, but 1% of 100 = 1 USD budget
      takeProfit: null,
      account: smallAccount,
      risk: normalRisk,
      now: "t",
    });

    // rawVolume = 1 / (10 * 100) = 0.001, floored to 0.01 -> real risk 10 USD
    expect(result.decision?.approvedVolume).toBe(0.01);
    expect(result.targetRiskUsd).toBeCloseTo(1);
    expect(result.realRiskUsd).toBeCloseTo(10);
    expect(result.floorApplied).toBe(true);
  });

  it("still reports distance and gates when the account is locked, but no size", () => {
    const lockedRisk: RiskStatus = {
      ...normalRisk,
      state: "locked",
      lockoutReason: "Daily loss guard",
    };
    const result = computeSizingPanel({
      entryPrice: 3300,
      stopLoss: 3290,
      takeProfit: null,
      account,
      risk: lockedRisk,
      now: "t",
    });

    expect(result.stopDistance).toBe(10);
    expect(result.decision?.approved).toBe(false);
    expect(result.decision?.reason).toContain("locked");
    expect(result.realRiskUsd).toBeNull();
    expect(result.dailyBudgetConsumedPercent).toBeNull();
    expect(result.gates).toBe(lockedRisk.gates);
  });

  it("returns nulls for an invalid stop (equal to entry) without computing a decision", () => {
    const result = computeSizingPanel({
      entryPrice: 3300,
      stopLoss: 3300,
      takeProfit: 3320,
      account,
      risk: normalRisk,
      now: "t",
    });

    expect(result.stopDistance).toBeNull();
    expect(result.decision).toBeNull();
    expect(result.rMultipleTarget).toBeNull();
  });

  it("computes the target R-multiple from entry/stop/take-profit alone", () => {
    const result = computeSizingPanel({
      entryPrice: 3300,
      stopLoss: 3290,
      takeProfit: 3320,
      account,
      risk: normalRisk,
      now: "t",
    });

    expect(result.rMultipleTarget).toBeCloseTo(2); // 20 reward / 10 risk
  });

  it("flags a take-profit placed on the wrong side of entry instead of returning a fake positive R", () => {
    // Long (stop below entry): a TP below entry is on the wrong side.
    const result = computeSizingPanel({
      entryPrice: 3300,
      stopLoss: 3290,
      takeProfit: 3295,
      account,
      risk: normalRisk,
      now: "t",
    });

    expect(result.takeProfitInvalid).toBe(true);
    expect(result.rMultipleTarget).toBeNull();
  });

  it("computes the daily-budget share against what remains today, not the total limit", () => {
    const bigAccount: AccountSummary = { ...account, balance: 100_000, equity: 100_000 };
    const mostlyUsedRisk: RiskStatus = { ...normalRisk, dailyLossUsedPercent: 4.5 }; // 4500 of a 5000 (5%) limit
    const result = computeSizingPanel({
      entryPrice: 3300,
      stopLoss: 3290, // 1% of 100_000 = 1000 USD target, sizes to exactly 1.0 lot, no floor
      takeProfit: null,
      account: bigAccount,
      risk: mostlyUsedRisk,
      now: "t",
    });

    expect(result.decision?.approvedVolume).toBe(1);
    expect(result.realRiskUsd).toBeCloseTo(1000);
    // Remaining budget is only 500 USD (5000 limit - 4500 already used): this
    // trade would burn all of it and then some, not a reassuring 20%.
    expect(result.dailyBudgetConsumedPercent).toBeCloseTo(200);
  });
});
