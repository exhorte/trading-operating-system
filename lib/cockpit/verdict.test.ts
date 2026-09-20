import { describe, expect, it } from "vitest";
import type { RiskGate, RiskStatus } from "@/lib/contracts/snapshots";
import { sessionVerdict, tightestHeadroom } from "./verdict";

function gate(gateId: string, state: RiskGate["state"]): RiskGate {
  return { gateId, label: gateId, state, detail: "" };
}

function risk(overrides: Partial<RiskStatus> = {}): RiskStatus {
  return {
    state: "normal",
    dailyLossLimitPercent: 5,
    dailyLossUsedPercent: 1,
    maxDrawdownLimitPercent: 10,
    maxDrawdownUsedPercent: 1,
    maxTradesPerDay: 6,
    tradesToday: 1,
    consecutiveLosses: 0,
    lockoutReason: null,
    lockoutUntil: null,
    gates: [gate("daily-loss", "open"), gate("session", "open")],
    ...overrides,
  };
}

describe("sessionVerdict", () => {
  it("is armed when every gate is open and the account is not locked", () => {
    const verdict = sessionVerdict(risk());
    expect(verdict.armed).toBe(true);
    expect(verdict.blocking).toEqual([]);
  });

  it("is not armed when a gate is blocked, and reports which", () => {
    const verdict = sessionVerdict(
      risk({ gates: [gate("daily-loss", "open"), gate("session", "blocked")] }),
    );
    expect(verdict.armed).toBe(false);
    expect(verdict.blocking.map((g) => g.gateId)).toEqual(["session"]);
  });

  // The case the two copies of this rule existed to cover: a ledger-held
  // lockout (T02a/T02c) while every individual gate still reads open.
  it("is not armed when the state is locked even with all gates open", () => {
    const verdict = sessionVerdict(risk({ state: "locked", lockoutReason: "kill switch" }));
    expect(verdict.armed).toBe(false);
    expect(verdict.blocking).toEqual([]);
    expect(verdict.lockoutReason).toBe("kill switch");
  });
});

describe("tightestHeadroom", () => {
  it("picks the limit with the largest consumed share, across units", () => {
    // daily loss 1/5 = 20%, drawdown 1/10 = 10%, trades 5/6 = 83%.
    const headroom = tightestHeadroom(risk({ tradesToday: 5 }));
    expect(headroom).toEqual({
      label: "trades du jour",
      remaining: "1 trade",
      usedRatio: 5 / 6,
    });
  });

  it("reports percentage-point limits in points", () => {
    const headroom = tightestHeadroom(risk({ dailyLossUsedPercent: 4 }));
    expect(headroom?.label).toBe("perte du jour");
    expect(headroom?.remaining).toBe("1.0 pts");
  });

  // Null tradesToday means "this source has no trade history", not "zero
  // trades taken" — counting it as a full budget would overstate the room.
  it("leaves the trade count out when the source has no trade history", () => {
    const headroom = tightestHeadroom(risk({ tradesToday: null, dailyLossUsedPercent: 2 }));
    expect(headroom?.label).toBe("perte du jour");
  });

  it("never reports negative headroom once a limit is breached", () => {
    const headroom = tightestHeadroom(risk({ dailyLossUsedPercent: 7 }));
    expect(headroom?.remaining).toBe("0.0 pts");
    expect(headroom?.usedRatio).toBe(1);
  });

  it("returns null when no limit has a usable budget", () => {
    expect(
      tightestHeadroom(
        risk({ dailyLossLimitPercent: 0, maxDrawdownLimitPercent: 0, tradesToday: null }),
      ),
    ).toBeNull();
  });
});
