import { describe, expect, it } from "vitest";
import {
  isTerminal,
  transition,
  type CommandLifecycleState,
} from "./execution-state";

describe("transition — happy path", () => {
  it("walks the full command lifecycle to RECONCILED", () => {
    let state: CommandLifecycleState = "COMMAND_CREATED";

    state = expectOk(transition(state, { kind: "RISK_APPROVED" }));
    expect(state).toBe("RISK_APPROVED");

    state = expectOk(transition(state, { kind: "SENT" }));
    expect(state).toBe("SENT_TO_MT5");

    state = expectOk(transition(state, { kind: "ACK_ACCEPTED" }));
    expect(state).toBe("RECEIVED");

    state = expectOk(transition(state, { kind: "VALIDATION_STARTED" }));
    expect(state).toBe("VALIDATING");

    state = expectOk(transition(state, { kind: "VALIDATION_PASSED" }));
    expect(state).toBe("EXECUTING");

    state = expectOk(transition(state, { kind: "EXECUTION_REPORTED" }));
    expect(state).toBe("EXECUTED");

    state = expectOk(
      transition(state, { kind: "RECONCILED", outcome: "executed" }),
    );
    expect(state).toBe("RECONCILED");
    expect(isTerminal(state)).toBe(true);
  });
});

describe("transition — UNKNOWN is first-class, not an error path", () => {
  it("enters UNKNOWN when the link is lost between send and ack", () => {
    const result = transition("SENT_TO_MT5", { kind: "LINK_LOST" });
    expect(result).toMatchObject({ ok: true, state: "UNKNOWN" });
  });

  it("enters UNKNOWN when the link is lost between order send and report", () => {
    const result = transition("EXECUTING", { kind: "EXECUTION_LINK_LOST" });
    expect(result).toMatchObject({ ok: true, state: "UNKNOWN" });
  });

  it("stays UNKNOWN when reconciliation is inconclusive — never guesses", () => {
    const result = transition("UNKNOWN", { kind: "RECONCILIATION_PENDING" });
    expect(result).toMatchObject({ ok: true, state: "UNKNOWN" });
  });

  it("resolves UNKNOWN only through RECONCILED", () => {
    const result = transition("UNKNOWN", {
      kind: "RECONCILED",
      outcome: "rejected",
    });
    expect(result).toMatchObject({ ok: true, state: "RECONCILED" });
  });

  it("REFUSES a replay from UNKNOWN into EXECUTING — the core ADR 0010 rule", () => {
    const result = transition("UNKNOWN", { kind: "EXECUTION_REPORTED" });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.from).toBe("UNKNOWN");
      expect(result.event).toBe("EXECUTION_REPORTED");
    }
  });

  it("refuses UNKNOWN -> RECEIVED (no automatic retry of the happy path)", () => {
    const result = transition("UNKNOWN", { kind: "ACK_ACCEPTED" });
    expect(result.ok).toBe(false);
  });
});

describe("transition — illegal moves are rejected, not silently allowed", () => {
  it("refuses to skip VALIDATING and jump straight to EXECUTED", () => {
    const result = transition("RECEIVED", { kind: "EXECUTION_REPORTED" });
    expect(result.ok).toBe(false);
  });

  it("refuses to cancel a command that is already EXECUTING", () => {
    const result = transition("EXECUTING", { kind: "CANCEL_REQUESTED" });
    expect(result.ok).toBe(false);
  });

  it("refuses to expire a command that is already EXECUTING", () => {
    const result = transition("EXECUTING", { kind: "EXPIRED" });
    expect(result.ok).toBe(false);
  });

  it.each([
    "REJECTED",
    "EXPIRED",
    "FAILED",
    "CANCELLED",
    "RECONCILED",
  ] as const)("refuses any event once in the terminal state %s", (state) => {
    const result = transition(state, { kind: "RISK_APPROVED" });
    expect(result.ok).toBe(false);
    expect(isTerminal(state)).toBe(true);
  });
});

describe("transition — rejection and expiry paths", () => {
  it("moves RISK_APPROVED -> FAILED when the agent cannot be reached", () => {
    const result = transition("RISK_APPROVED", {
      kind: "SEND_FAILED",
      detail: "agent unreachable",
    });
    expect(result).toMatchObject({ ok: true, state: "FAILED" });
  });

  it("moves VALIDATING -> REJECTED on a failed local barrier (e.g. ACCOUNT_MISMATCH)", () => {
    const result = transition("VALIDATING", {
      kind: "VALIDATION_FAILED",
      detail: "ACCOUNT_MISMATCH",
    });
    expect(result).toMatchObject({ ok: true, state: "REJECTED" });
  });

  it("expires a command still waiting on risk approval past its TTL", () => {
    const result = transition("COMMAND_CREATED", { kind: "EXPIRED" });
    expect(result).toMatchObject({ ok: true, state: "EXPIRED" });
  });
});

function expectOk(result: ReturnType<typeof transition>): CommandLifecycleState {
  expect(result.ok).toBe(true);
  if (!result.ok) {
    throw new Error(result.reason);
  }
  return result.state;
}
