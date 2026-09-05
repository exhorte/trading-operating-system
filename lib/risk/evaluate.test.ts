import { describe, expect, it } from "vitest";
import { evaluateRiskState } from "./evaluate";
import { defaultRiskPolicy } from "./policy";
import type { RiskEvaluationInput } from "./types";

const base: RiskEvaluationInput = {
  policy: defaultRiskPolicy("acc-1"),
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

describe("evaluateRiskState", () => {
  it("is normal with a flat account inside all limits", () => {
    const state = evaluateRiskState(base);
    expect(state.mode).toBe("normal");
    expect(state.lockoutReason).toBeNull();
    expect(state.gates.every((g) => g.state === "open")).toBe(true);
  });

  it("escalates to warning past 60% of the daily-loss limit", () => {
    // 5% limit -> warn at 3%. Lose 35 on 1000 = 3.5%.
    const state = evaluateRiskState({ ...base, equity: 965 });
    expect(state.mode).toBe("warning");
  });

  it("locks the account when the daily-loss limit is breached", () => {
    // lose 55 on 1000 = 5.5% >= 5%
    const state = evaluateRiskState({ ...base, equity: 945 });
    expect(state.mode).toBe("locked");
    expect(state.lockoutReason).toContain("Daily loss");
    expect(state.gates.find((g) => g.gateId === "gate-daily-loss")?.state).toBe("blocked");
  });

  it("blocks entries (not a lockout) when the session is closed", () => {
    const state = evaluateRiskState({ ...base, session: "new_york_pm", sessionTradingEnabled: false });
    expect(state.mode).toBe("normal"); // session is an entry gate, not a lockout
    expect(state.gates.find((g) => g.gateId === "gate-session")?.state).toBe("blocked");
  });

  it("reports n/a (open) for trade-history gates when counts are unknown", () => {
    const state = evaluateRiskState({ ...base, tradesToday: null, consecutiveLosses: null });
    expect(state.tradesToday).toBeNull();
    expect(state.gates.find((g) => g.gateId === "gate-max-trades")?.detail).toBe("n/a (observe)");
    expect(state.mode).toBe("normal");
  });

  it("locks on too many consecutive losses", () => {
    const state = evaluateRiskState({ ...base, consecutiveLosses: 3 });
    expect(state.mode).toBe("locked");
    expect(state.lockoutReason).toContain("Consecutive losses");
  });
});
