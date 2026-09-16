import { describe, expect, it } from "vitest";
import { detectLockoutViolation, detectSessionViolation, detectSizeViolation } from "./violations";
import { DEFAULT_SESSION_WINDOWS } from "@/lib/analysis/config";
import type { LockoutWindow } from "./violations";

describe("detectLockoutViolation", () => {
  /** The real 2026-09-15 case (risk_lockouts, account 477029930) — the
   *  fiche's own success criterion: this exact trade must come back
   *  flagged. Kill switch fired 09:34:44.663Z, cleared 09:37:18.648Z,
   *  the EURUSDm trade (position 3230177984) opened at 09:36:00Z, inside
   *  the window. */
  const realKillSwitchLockout: LockoutWindow = {
    lockoutId: "lockout-mu2h6tvb-8qosw0",
    reason: "Kill switch manuel",
    since: "2026-09-15T09:34:44.663Z",
    until: null,
    clearedAt: "2026-09-15T09:37:18.648Z",
  };

  it("flags the real 2026-09-15 trade opened during the active kill-switch lockout", () => {
    const result = detectLockoutViolation("2026-09-15T09:36:00.000Z", [realKillSwitchLockout]);
    expect(result).not.toBeNull();
    expect(result?.type).toBe("LOCKOUT_ACTIVE");
    expect(result?.detail).toContain("Kill switch manuel");
  });

  it("does not flag a trade opened before the lockout started", () => {
    const result = detectLockoutViolation("2026-09-15T09:30:00.000Z", [realKillSwitchLockout]);
    expect(result).toBeNull();
  });

  it("does not flag a trade opened after the lockout was cleared", () => {
    const result = detectLockoutViolation("2026-09-15T09:40:00.000Z", [realKillSwitchLockout]);
    expect(result).toBeNull();
  });

  it("does not flag a trade opened after an until-based (auto-expiring) lockout has expired", () => {
    // Synthetic — T02b's 30-min consecutive-loss pause has never actually
    // triggered live yet (state.md, "Ce qui bloque"), so there is no real
    // `until`-bearing row to draw from. Exercises the same branch anyway.
    const timedPause: LockoutWindow = {
      lockoutId: "lockout-synthetic",
      reason: "Daily loss guard",
      since: "2026-09-16T10:00:00.000Z",
      until: "2026-09-16T10:30:00.000Z",
      clearedAt: null,
    };
    const result = detectLockoutViolation("2026-09-16T10:31:00.000Z", [timedPause]);
    expect(result).toBeNull();
  });

  it("flags a trade opened before an until-based lockout expires", () => {
    const timedPause: LockoutWindow = {
      lockoutId: "lockout-synthetic",
      reason: "Daily loss guard",
      since: "2026-09-16T10:00:00.000Z",
      until: "2026-09-16T10:30:00.000Z",
      clearedAt: null,
    };
    const result = detectLockoutViolation("2026-09-16T10:15:00.000Z", [timedPause]);
    expect(result?.type).toBe("LOCKOUT_ACTIVE");
  });

  it("returns null with no lockouts at all", () => {
    expect(detectLockoutViolation("2026-09-15T09:36:00.000Z", [])).toBeNull();
  });
});

describe("detectSessionViolation", () => {
  it("does not flag a trade opened during London (tradingEnabled)", () => {
    // 09:00 UTC falls inside the London window (07:00-12:00).
    const result = detectSessionViolation("2026-09-15T09:00:00.000Z", DEFAULT_SESSION_WINDOWS);
    expect(result).toBeNull();
  });

  it("flags a trade opened during Asia (tradingEnabled: false)", () => {
    // 01:00 UTC falls inside the wrapping Asia window (23:00-07:00).
    const result = detectSessionViolation("2026-09-15T01:00:00.000Z", DEFAULT_SESSION_WINDOWS);
    expect(result?.type).toBe("SESSION_WINDOW");
    expect(result?.detail).toContain("asia");
  });

  it("flags a trade opened during NY PM (tradingEnabled: false)", () => {
    const result = detectSessionViolation("2026-09-15T17:00:00.000Z", DEFAULT_SESSION_WINDOWS);
    expect(result?.type).toBe("SESSION_WINDOW");
  });
});

describe("detectSizeViolation", () => {
  const policy = { maxRiskPerTradePercent: 1 };
  // EURUSD-like metadata (lib/market/symbols/registry.ts).
  const metadata = { tickSize: 0.00001, tickValue: 1.0 };
  const balance = 10_000;

  it("does not flag a trade within the risk budget", () => {
    // riskUsd = 100; stopDistance 0.0010 -> 100 ticks * 1.0 = 100 USD/lot -> maxVolume 1.0
    const result = detectSizeViolation(0.5, 1.1500, 1.1490, balance, policy, metadata);
    expect(result).toBeNull();
  });

  it("flags a trade clearly over the risk budget", () => {
    const result = detectSizeViolation(5.0, 1.1500, 1.1490, balance, policy, metadata);
    expect(result?.type).toBe("SIZE_POLICY");
  });

  it("does not flag a trade right at the approved max (rounding tolerance)", () => {
    // maxVolume is exactly 1.0 lot here; evaluateSignalRisk would floor to
    // 1.00 too, so this must not false-positive.
    const result = detectSizeViolation(1.0, 1.1500, 1.1490, balance, policy, metadata);
    expect(result).toBeNull();
  });

  it("returns null when no stop was captured (0 = MT5's unset convention)", () => {
    const result = detectSizeViolation(5.0, 1.1500, 0, balance, policy, metadata);
    expect(result).toBeNull();
  });
});
