import { describe, expect, it } from "vitest";
import { makeEnvelope } from "@/lib/mock/envelope";
import type { ExecutionReport } from "@/lib/contracts/snapshots";
import { CockpitStore } from "./store";

function report(overrides: Partial<ExecutionReport> = {}): ExecutionReport {
  return {
    reportId: "cmd-1:SIMULATED:1790000000000",
    commandId: "cmd-1",
    correlationId: "cmd-1",
    accountId: "477029930",
    agentId: "mt5-execution-agent-1001",
    symbol: "EURUSDm",
    side: "buy",
    status: "simulated",
    detail: "SIMULATED 0.01 lot BUY EURUSDm",
    reportedAt: "2026-09-26T08:00:00.000Z",
    ...overrides,
  };
}

describe("CockpitStore — execution report feed", () => {
  it("keeps one entry per report id: a report the agent sends again after a reconnection is not shown twice", () => {
    const store = new CockpitStore();
    store.apply(makeEnvelope("execution.order.simulated", "mt5-gateway", { report: report() }));
    store.apply(makeEnvelope("execution.order.simulated", "mt5-gateway", { report: report({ detail: "replayed" }) }));

    const feed = store.getSnapshot().executionReports;
    expect(feed).toHaveLength(1);
    expect(feed[0].detail).toBe("replayed");
  });

  it("shows a refused order: the agent's REJECTED report travels as execution.command.rejected", () => {
    const store = new CockpitStore();
    const rejected = report({ reportId: "cmd-2:REJECTED:1", commandId: "cmd-2", status: "rejected", detail: "HALTED: …" });
    store.apply(makeEnvelope("execution.command.rejected", "mt5-gateway", { report: rejected }));

    expect(store.getSnapshot().executionReports.map((r) => r.commandId)).toEqual(["cmd-2"]);
  });

  it("leaves a rejection ack out of the feed — an ack is not a report", () => {
    const store = new CockpitStore();
    const ack = { commandId: "cmd-3", agentId: "gateway", status: "rejected", reason: "agent unreachable", receivedAt: "2026-09-26T08:00:00Z" };
    store.apply(makeEnvelope("execution.command.rejected", "cockpit-hub", { ack }));

    expect(store.getSnapshot().executionReports).toEqual([]);
  });

  it("shows failures and partial fills, newest first", () => {
    const store = new CockpitStore();
    store.apply(makeEnvelope("execution.order.partially_filled", "mt5-gateway", { report: report({ reportId: "a", commandId: "a" }) }));
    store.apply(makeEnvelope("execution.order.failed", "mt5-gateway", { report: report({ reportId: "b", commandId: "b" }) }));

    expect(store.getSnapshot().executionReports.map((r) => r.reportId)).toEqual(["b", "a"]);
  });
});
