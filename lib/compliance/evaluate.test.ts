import { describe, expect, it } from "vitest";
import { evaluateTrade, complianceRate } from "./evaluate";
import { DEFAULT_SESSION_WINDOWS } from "@/lib/analysis/config";
import type { LockoutWindow } from "./violations";
import type { ComplianceTradeInput } from "./evaluate";

const policy = { maxRiskPerTradePercent: 1 };

describe("evaluateTrade", () => {
  const realKillSwitchLockout: LockoutWindow = {
    lockoutId: "lockout-mu2h6tvb-8qosw0",
    reason: "Kill switch manuel",
    since: "2026-09-15T09:34:44.663Z",
    until: null,
    clearedAt: "2026-09-15T09:37:18.648Z",
  };

  const realTrade: ComplianceTradeInput = {
    brokerPositionId: "3230177984",
    symbol: "EURUSD",
    openedAt: "2026-09-15T09:36:00.000Z",
    volume: 0.05,
    entryPrice: 1.15339,
    stopLoss: 0, // real data: no stop was ever set on this trade
  };

  it("returns the real 2026-09-15 lockout violation and nothing else (no stop captured)", () => {
    const violations = evaluateTrade(realTrade, [realKillSwitchLockout], DEFAULT_SESSION_WINDOWS, 10_000, policy);
    expect(violations).toHaveLength(1);
    expect(violations[0].type).toBe("LOCKOUT_ACTIVE");
  });

  it("returns no violations when openedAt is unknown", () => {
    const violations = evaluateTrade(
      { ...realTrade, openedAt: null },
      [realKillSwitchLockout],
      DEFAULT_SESSION_WINDOWS,
      10_000,
      policy,
    );
    expect(violations).toEqual([]);
  });

  it("returns both a lockout and a session violation when both apply", () => {
    const nightLockout: LockoutWindow = {
      lockoutId: "lockout-synthetic",
      reason: "Daily loss guard",
      since: "2026-09-16T00:00:00.000Z",
      until: null,
      clearedAt: null,
    };
    const trade: ComplianceTradeInput = {
      brokerPositionId: "synthetic-1",
      symbol: "EURUSD",
      openedAt: "2026-09-16T01:00:00.000Z", // inside Asia (disabled) AND the lockout
      volume: 0.05,
      entryPrice: null,
      stopLoss: null,
    };
    const violations = evaluateTrade(trade, [nightLockout], DEFAULT_SESSION_WINDOWS, 10_000, policy);
    expect(violations.map((v) => v.type).sort()).toEqual(["LOCKOUT_ACTIVE", "SESSION_WINDOW"]);
  });

  it("skips the size check when balance is null", () => {
    const oversized: ComplianceTradeInput = {
      brokerPositionId: "synthetic-2",
      symbol: "EURUSD",
      openedAt: "2026-09-15T09:00:00.000Z", // London, no lockout active
      volume: 50,
      entryPrice: 1.1500,
      stopLoss: 1.1490,
    };
    const violations = evaluateTrade(oversized, [], DEFAULT_SESSION_WINDOWS, null, policy);
    expect(violations).toEqual([]);
  });

  it("flags an oversized trade when balance is known", () => {
    const oversized: ComplianceTradeInput = {
      brokerPositionId: "synthetic-3",
      symbol: "EURUSD",
      openedAt: "2026-09-15T09:00:00.000Z",
      volume: 50,
      entryPrice: 1.1500,
      stopLoss: 1.1490,
    };
    const violations = evaluateTrade(oversized, [], DEFAULT_SESSION_WINDOWS, 10_000, policy);
    expect(violations).toHaveLength(1);
    expect(violations[0].type).toBe("SIZE_POLICY");
  });
});

describe("complianceRate", () => {
  it("returns 1 for an empty week — nothing to violate, not a bad score", () => {
    expect(complianceRate([])).toBe(1);
  });

  it("returns 1 when every trade is clean", () => {
    expect(complianceRate([[], [], []])).toBe(1);
  });

  it("returns the fraction of trades with zero violations", () => {
    const withLockout = [{ type: "LOCKOUT_ACTIVE" as const, detail: "x" }];
    expect(complianceRate([[], withLockout, [], []])).toBe(0.75);
  });

  it("returns 0 when every trade has at least one violation", () => {
    const v = [{ type: "SESSION_WINDOW" as const, detail: "x" }];
    expect(complianceRate([v, v])).toBe(0);
  });
});
