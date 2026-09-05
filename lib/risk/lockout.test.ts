import { describe, expect, it } from "vitest";
import {
  applyActiveLockout,
  detectNewLockout,
  KILL_SWITCH_REASON,
  shouldAutoClearForNewDay,
  type ActiveLockout,
} from "./lockout";
import type { RiskState } from "@/lib/domain/risk";

const lockedState: RiskState = {
  accountId: "acc-1",
  mode: "locked",
  dailyLossUsedPercent: 5.5,
  maxDrawdownUsedPercent: 0,
  openRiskPercent: 0,
  tradesToday: 3,
  consecutiveLosses: 0,
  lockoutReason: "Daily loss guard",
  lockoutUntil: null,
  gates: [],
  evaluatedAt: "t",
};

const normalState: RiskState = { ...lockedState, mode: "normal", lockoutReason: null };

describe("detectNewLockout", () => {
  it("fires when the state just crossed into locked with no lockout on record", () => {
    expect(detectNewLockout(lockedState, null)).toEqual({ reason: "Daily loss guard" });
  });

  it("does not re-fire while already locked and already recorded", () => {
    const active: ActiveLockout = { lockoutId: "l1", reason: "Daily loss guard", since: "t", until: null };
    expect(detectNewLockout(lockedState, active)).toBeNull();
  });

  it("does not fire for a normal/warning state", () => {
    expect(detectNewLockout(normalState, null)).toBeNull();
  });
});

describe("applyActiveLockout", () => {
  it("overrides a freshly-recovered live state while the ledger still says locked", () => {
    const active: ActiveLockout = { lockoutId: "l1", reason: "Daily loss guard", since: "t", until: null };
    // Gates recovered (e.g. equity ticked back up) but the stored lock must still hold.
    const merged = applyActiveLockout(normalState, active);
    expect(merged.mode).toBe("locked");
    expect(merged.lockoutReason).toBe("Daily loss guard");
  });

  it("passes the state through unchanged when there is no active lockout", () => {
    expect(applyActiveLockout(normalState, null)).toBe(normalState);
  });
});

describe("shouldAutoClearForNewDay", () => {
  it("clears a daily-loss lockout once a new day anchor arrives", () => {
    const active: ActiveLockout = {
      lockoutId: "l1",
      reason: "Daily loss guard",
      since: "2026-09-04T22:00:00.000Z",
      until: null,
    };
    expect(shouldAutoClearForNewDay(active, "2026-09-04T21:00:00.000Z")).toBe(false); // lock is after this anchor
    expect(shouldAutoClearForNewDay(active, "2026-09-05T21:00:00.000Z")).toBe(true); // next day's anchor
  });

  it("never auto-clears the kill switch, even across a day rollover", () => {
    const active: ActiveLockout = {
      lockoutId: "l1",
      reason: KILL_SWITCH_REASON,
      since: "2026-09-04T22:00:00.000Z",
      until: null,
    };
    expect(shouldAutoClearForNewDay(active, "2026-09-05T21:00:00.000Z")).toBe(false);
  });
});
