import { describe, expect, it } from "vitest";
import { makeEnvelope } from "@/lib/mock/envelope";
import type { ExecutionAgentStatus, ExecutionReport } from "@/lib/contracts/snapshots";
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

function agentStatus(overrides: Partial<ExecutionAgentStatus> = {}): ExecutionAgentStatus {
  return {
    accountId: "477029930",
    agentId: "mt5-execution-agent-1001",
    agentVersion: "1.10",
    buildId: "1.10 2026.09.26 04:00",
    mode: "observe",
    modeCeiling: "observe",
    identity: "ok",
    expectedAccountId: null,
    server: "Exness-MT5Trial9",
    tradeMode: "demo",
    marginMode: "hedging",
    fifoClose: false,
    terminalTradeAllowed: true,
    expertTradeAllowed: false,
    accountTradeExpert: true,
    accountTradeAllowed: true,
    tradable: false,
    closable: false,
    halted: false,
    attachedExperts: [],
    gatewaySilentMs: 1000,
    lastHeartbeatTime: 1790000000000,
    ...overrides,
  };
}

function withAccount(store: CockpitStore, accountId: string): void {
  store.hydrate({
    account: {
      accountId,
      label: accountId,
      broker: "Exness",
      currency: "USD",
      balance: 1000,
      equity: 1000,
      dailyPnl: 0,
      dailyDrawdownPercent: 0,
      totalDrawdownPercent: 0,
      openRiskPercent: 0,
    },
  });
}

describe("CockpitStore — execution agent status (I2)", () => {
  it("keeps the status of the agent serving the account on screen", () => {
    const store = new CockpitStore();
    withAccount(store, "477029930");
    store.apply(makeEnvelope("execution.agent.status", "mt5-gateway", { status: agentStatus({ halted: true }) }, "477029930"));
    expect(store.getSnapshot().executionAgentStatus?.halted).toBe(true);
  });

  it("ignores another login's agent", () => {
    const store = new CockpitStore();
    withAccount(store, "477029930");
    store.apply(makeEnvelope("execution.agent.status", "mt5-gateway", { status: agentStatus({ accountId: "999" }) }, "999"));
    expect(store.getSnapshot().executionAgentStatus).toBeNull();
  });

  it("forgets the status when that account's agent goes away, or when no agent is connected", () => {
    const store = new CockpitStore();
    withAccount(store, "477029930");
    store.apply(makeEnvelope("execution.agent.status", "mt5-gateway", { status: agentStatus() }, "477029930"));
    store.apply(makeEnvelope("execution.agent.status", "mt5-gateway", { status: null }, "999"));
    expect(store.getSnapshot().executionAgentStatus).not.toBeNull();

    store.apply(makeEnvelope("execution.agent.status", "mt5-gateway", { status: null }, "477029930"));
    expect(store.getSnapshot().executionAgentStatus).toBeNull();

    store.apply(makeEnvelope("execution.agent.status", "mt5-gateway", { status: agentStatus() }, "477029930"));
    store.apply(makeEnvelope("execution.agent.connection", "mt5-gateway", { connected: false }));
    expect(store.getSnapshot().executionAgentStatus).toBeNull();
    expect(store.getSnapshot().executionAgentConnected).toBe(false);
  });
});

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
