import { describe, expect, it } from "vitest";
import {
  applyActiveLockout,
  CONSECUTIVE_LOSS_REASON,
  detectConsecutiveLossPause,
  detectNewLockout,
  isLockoutExpired,
  KILL_SWITCH_REASON,
  shouldAutoClearForNewDay,
  type ActiveLockout,
} from "./lockout";
import type { RiskState } from "@/lib/domain/risk";

const NOW = "2026-09-05T10:00:00.000Z";

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
    const merged = applyActiveLockout(normalState, active, NOW);
    expect(merged.mode).toBe("locked");
    expect(merged.lockoutReason).toBe("Daily loss guard");
  });

  it("passes the state through unchanged when there is no active lockout", () => {
    expect(applyActiveLockout(normalState, null, NOW)).toBe(normalState);
  });

  it("T02b: passes the state through unchanged once a timed pause has expired", () => {
    const expired: ActiveLockout = {
      lockoutId: "l2",
      reason: CONSECUTIVE_LOSS_REASON,
      since: "2026-09-05T09:00:00.000Z",
      until: "2026-09-05T09:30:00.000Z",
    };
    expect(applyActiveLockout(normalState, expired, NOW)).toBe(normalState);
  });

  it("T02b: still locks while a timed pause has not yet expired", () => {
    const active: ActiveLockout = {
      lockoutId: "l3",
      reason: CONSECUTIVE_LOSS_REASON,
      since: "2026-09-05T09:55:00.000Z",
      until: "2026-09-05T10:25:00.000Z",
    };
    const merged = applyActiveLockout(normalState, active, NOW);
    expect(merged.mode).toBe("locked");
    expect(merged.lockoutUntil).toBe("2026-09-05T10:25:00.000Z");
  });
});

describe("isLockoutExpired", () => {
  it("is false for a manual/next-day lockout (until === null)", () => {
    const active: ActiveLockout = { lockoutId: "l1", reason: KILL_SWITCH_REASON, since: "t", until: null };
    expect(isLockoutExpired(active, NOW)).toBe(false);
  });

  it("is true once now reaches the pause's until", () => {
    const active: ActiveLockout = {
      lockoutId: "l2",
      reason: CONSECUTIVE_LOSS_REASON,
      since: "t",
      until: "2026-09-05T10:00:00.000Z",
    };
    expect(isLockoutExpired(active, NOW)).toBe(true);
  });
});

describe("detectConsecutiveLossPause", () => {
  const consecutiveLossBlocked: RiskState = {
    ...normalState,
    gates: [{ gateId: "gate-consec-loss", label: "Consecutive losses", state: "blocked", detail: "2/2" }],
  };

  it("fires a 30-minute pause from the last loss when the consecutive-loss gate is blocked", () => {
    const result = detectConsecutiveLossPause(consecutiveLossBlocked, null, "2026-09-05T09:45:00.000Z", 30);
    expect(result).toEqual({ reason: CONSECUTIVE_LOSS_REASON, until: "2026-09-05T10:15:00.000Z" });
  });

  it("does not fire while a lockout is already on record, even for a different reason", () => {
    const active: ActiveLockout = { lockoutId: "l1", reason: "Daily loss guard", since: "t", until: null };
    expect(detectConsecutiveLossPause(consecutiveLossBlocked, active, "2026-09-05T09:45:00.000Z", 30)).toBeNull();
  });

  it("does not fire when the consecutive-loss gate is not blocked", () => {
    expect(detectConsecutiveLossPause(normalState, null, "2026-09-05T09:45:00.000Z", 30)).toBeNull();
  });

  it("does not fire without a known last-loss timestamp", () => {
    expect(detectConsecutiveLossPause(consecutiveLossBlocked, null, null, 30)).toBeNull();
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
