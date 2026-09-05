import { describe, expect, it } from "vitest";
import { CockpitStore } from "./store";
import { makeEnvelope } from "@/lib/mock/envelope";
import type {
  CommandAckPayload,
  PlaceOrderCommandPayload,
} from "@/lib/contracts/commands";
import type {
  ExecutionReportPayload,
  SignalCreatedPayload,
  TicketCreatedPayload,
} from "@/lib/contracts/events";
import type { PlaceOrderCommand } from "@/lib/domain/execution";
import type { PreTradeTicket } from "@/lib/domain/ticket";

const command: PlaceOrderCommand = {
  kind: "place_order",
  commandId: "cmd-sig-201",
  accountId: "acc",
  agentId: "mt5-observer-1",
  riskApprovalId: "risk-sig-201",
  expiresAt: "2026-07-11T10:01:00.000Z",
  issuedAt: "2026-07-11T10:00:00.000Z",
  symbol: "XAUUSDm",
  side: "buy",
  orderType: "market",
  volume: 0.02,
  limitPrice: null,
  stopLoss: 4048,
  takeProfit: 4063,
  signalId: "sig-201",
  strategyId: "ict-silver-bullet-v1",
};

function storeWithSignalAndCommand(): CockpitStore {
  const store = new CockpitStore();
  store.apply(
    makeEnvelope<SignalCreatedPayload>("strategy.signal.created", "test", {
      signal: {
        signalId: "sig-201",
        symbol: "XAUUSDm",
        strategyId: "ict-silver-bullet-v1",
        side: "buy",
        status: "approved",
        entryPrice: 4053,
        stopLoss: 4048,
        takeProfit: 4063,
        score: 6,
        maxScore: 10,
        contextSummary: "test",
        riskDecision: "Approved",
        expiresAt: "t",
        createdAt: "t",
      },
    }),
  );
  store.apply(
    makeEnvelope<PlaceOrderCommandPayload>("execution.command.place_order", "test", {
      command,
    }),
  );
  return store;
}

function ack(store: CockpitStore, status: "accepted" | "rejected" | "duplicate" | "expired", reason: string | null) {
  store.apply(
    makeEnvelope<CommandAckPayload>(
      status === "accepted" || status === "duplicate"
        ? "execution.command.acknowledged"
        : "execution.command.rejected",
      "test",
      {
        ack: {
          commandId: "cmd-sig-201",
          agentId: "mt5-observer-1",
          status,
          reason,
          receivedAt: "t",
        },
      },
    ),
  );
}

describe("command lifecycle in the store", () => {
  it("registers the command and marks the signal commanded", () => {
    const store = storeWithSignalAndCommand();
    expect(store.getSnapshot().commands["cmd-sig-201"]).toMatchObject({
      status: "sent",
      volume: 0.02,
      riskApprovalId: "risk-sig-201",
    });
    expect(store.getSnapshot().signals[0].status).toBe("commanded");
  });

  it("accepted ack → acknowledged; duplicate ack is a confirmation too", () => {
    const store = storeWithSignalAndCommand();
    ack(store, "accepted", null);
    expect(store.getSnapshot().commands["cmd-sig-201"].status).toBe("acknowledged");
    expect(store.getSnapshot().signals[0].status).toBe("acknowledged");

    const store2 = storeWithSignalAndCommand();
    ack(store2, "duplicate", "already processed");
    expect(store2.getSnapshot().commands["cmd-sig-201"].status).toBe("acknowledged");
  });

  it("rejected/expired ack terminates the command — and never produces a fill", () => {
    const store = storeWithSignalAndCommand();
    ack(store, "rejected", "volume out of bounds");
    expect(store.getSnapshot().commands["cmd-sig-201"].status).toBe("rejected");
    expect(store.getSnapshot().signals[0].status).toBe("rejected");
    expect(store.getSnapshot().executionReports).toHaveLength(0);

    const store2 = storeWithSignalAndCommand();
    ack(store2, "expired", "past expiresAt");
    expect(store2.getSnapshot().commands["cmd-sig-201"].status).toBe("expired");
    expect(store2.getSnapshot().signals[0].status).toBe("expired");
    expect(store2.getSnapshot().executionReports).toHaveLength(0);
  });

  it("SIMULATED report → feed entry + command/signal reported", () => {
    const store = storeWithSignalAndCommand();
    ack(store, "accepted", null);
    store.apply(
      makeEnvelope<ExecutionReportPayload>("execution.order.simulated", "test", {
        report: {
          reportId: "rep-1",
          commandId: "cmd-sig-201",
          correlationId: "cmd-sig-201",
          accountId: "acc",
          agentId: "mt5-observer-1",
          symbol: "XAUUSDm",
          side: "buy",
          status: "simulated",
          detail: "SIMULATED 0.02 lot (observe mode, no broker order)",
          reportedAt: "t",
        },
      }),
    );
    const snap = store.getSnapshot();
    expect(snap.executionReports[0].status).toBe("simulated");
    expect(snap.commands["cmd-sig-201"].status).toBe("reported");
    expect(snap.signals[0].status).toBe("reported");
  });

  it("timeout after the single retry → failed, no fill", () => {
    const store = storeWithSignalAndCommand();
    store.markCommandRetried("cmd-sig-201");
    expect(store.getSnapshot().commands["cmd-sig-201"].status).toBe("retried");
    store.markCommandFailed("cmd-sig-201", "no ack within timeout");
    expect(store.getSnapshot().commands["cmd-sig-201"].status).toBe("failed");
    expect(store.getSnapshot().executionReports).toHaveLength(0);
  });

  it("markCommandFailed never downgrades an acknowledged/reported command", () => {
    const store = storeWithSignalAndCommand();
    ack(store, "accepted", null);
    store.markCommandFailed("cmd-sig-201", "late timeout");
    expect(store.getSnapshot().commands["cmd-sig-201"].status).toBe("acknowledged");
  });
});

const ticket: PreTradeTicket = {
  ticketId: "ticket-1",
  accountId: "acc-1",
  symbol: "XAUUSD",
  setup: "fvg",
  bias: "long",
  entryPrice: 3300,
  stopLoss: 3290,
  invalidation: 3290,
  confidence: 4,
  takeProfit: 3320,
  targetVolume: 0.02,
  targetRiskUsd: 20,
  createdAt: "t",
};

describe("T04 ticket echo in the store", () => {
  it("records the ticketId once it echoes back through the event stream", () => {
    const store = new CockpitStore();
    expect(store.getSnapshot().confirmedTicketIds).toEqual([]);
    store.apply(makeEnvelope<TicketCreatedPayload>("journal.ticket.created", "test", { ticket }));
    expect(store.getSnapshot().confirmedTicketIds).toEqual(["ticket-1"]);
  });

  it("never confirms a ticket that was never echoed (silent refusal/drop stays unconfirmed)", () => {
    const store = new CockpitStore();
    // Nothing applied: this is what a whitelist refusal, an oversized
    // envelope, or a dropped persistence write all look like from the store.
    expect(store.getSnapshot().confirmedTicketIds).not.toContain("ticket-1");
  });
});
