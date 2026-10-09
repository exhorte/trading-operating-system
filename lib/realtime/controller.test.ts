import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CockpitEvent } from "@/lib/api/generated";
import type { SocketState } from "@/lib/websocket/cockpit-socket";
import { CockpitController, SETTLE_MS, type SocketPort } from "./controller";
import { CockpitStore } from "./store";
import { autonomy, command, frame, snapshotFrame } from "./test-fixtures";

const ID = "exness-1000001";

class FakePort implements SocketPort {
  started = 0;

  stopped = 0;

  resyncs = 0;

  constructor(
    readonly onFrame: (frame: CockpitEvent) => void,
    readonly onState: (state: SocketState, issue: string | null) => void,
  ) {}

  start(): void {
    this.started += 1;
  }

  stop(): void {
    this.stopped += 1;
  }

  resync(): void {
    this.resyncs += 1;
  }
}

function rig() {
  const store = new CockpitStore();
  const call = vi.fn();
  const warn = vi.fn();
  const ports: FakePort[] = [];
  const controller = new CockpitController(store, {
    call: call as never,
    warn,
    createSocket: (options) => {
      const port = new FakePort(options.onFrame, options.onState);
      ports.push(port);
      return port;
    },
  });
  return { store, call, warn, ports, controller };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the stream", () => {
  it("starts one socket however often it is asked, and feeds the store with its frames and its state", () => {
    const { store, ports, controller } = rig();
    controller.start();
    controller.start();
    expect(ports).toHaveLength(1);
    expect(ports[0].started).toBe(1);

    ports[0].onState("connected", null);
    ports[0].onFrame(snapshotFrame());
    expect(store.getSnapshot().connection).toBe("connected");
    expect(store.getSnapshot().activeAccountId).toBe(ID);

    ports[0].onState("reconnecting", "le cœur ne répond pas");
    expect(store.getSnapshot()).toMatchObject({ connection: "reconnecting", connectionIssue: "le cœur ne répond pas" });
  });

  it("stops the socket and forgets what it was about to read", async () => {
    const { ports, controller, call } = rig();
    controller.start();
    ports[0].onFrame(snapshotFrame());
    ports[0].onFrame(frame("autonomy.halted", { reason: "x" }));
    controller.stop();
    expect(ports[0].stopped).toBe(1);
    await vi.advanceTimersByTimeAsync(SETTLE_MS * 4);
    expect(call).not.toHaveBeenCalled();
    controller.start(); // and it can be started again
    expect(ports).toHaveLength(2);
  });
});

describe("the follow-up reads", () => {
  it("joins a burst of registry events into one resync, after the burst", async () => {
    const { ports, controller } = rig();
    controller.start();
    ports[0].onFrame(snapshotFrame());
    ports[0].onFrame(frame("account.connected", { server: "s", currency: "USD", environment: "DEMO" }, { accountId: ID }));
    ports[0].onFrame(frame("account.active_changed", { previous: null, current: ID }));
    ports[0].onFrame(frame("account.rules_changed", { versionId: "v", deferred: false, reasons: [] }, { accountId: ID }));
    expect(ports[0].resyncs).toBe(0);
    await vi.advanceTimersByTimeAsync(SETTLE_MS);
    expect(ports[0].resyncs).toBe(1);
  });

  it("re-reads the commands of the account an execution event is about", async () => {
    const { store, ports, controller, call } = rig();
    call.mockResolvedValue([command("c9", { state: "EXECUTED" })]);
    controller.start();
    ports[0].onFrame(snapshotFrame());
    ports[0].onFrame(frame("execution.acknowledged", { commandId: "c9", status: "ACCEPTED", reason: null }, { accountId: ID }));
    ports[0].onFrame(frame("execution.reported", { commandId: "c9" } as never, { accountId: ID }));
    await vi.advanceTimersByTimeAsync(SETTLE_MS);
    expect(call).toHaveBeenCalledTimes(1);
    expect(call).toHaveBeenCalledWith("execution_commands", { query: { accountId: ID, limit: 20 } });
    expect(store.getSnapshot().commands.map((c) => [c.request.commandId, c.state])).toEqual([["c9", "EXECUTED"]]);
  });

  it("re-reads the autonomy overview when the mode moves", async () => {
    const { store, ports, controller, call } = rig();
    call.mockResolvedValue(autonomy({ effectiveMode: "HALTED" }));
    controller.start();
    ports[0].onFrame(snapshotFrame());
    ports[0].onFrame(frame("autonomy.halted", { reason: "x" }));
    await vi.advanceTimersByTimeAsync(SETTLE_MS);
    expect(call).toHaveBeenCalledWith("autonomy_state");
    expect(store.getSnapshot().autonomy?.effectiveMode).toBe("HALTED");
  });

  it("does not let a failed read break the stream: it is logged, and the next event or snapshot corrects it", async () => {
    const { store, ports, controller, call, warn } = rig();
    call.mockRejectedValue(new Error("core down"));
    controller.start();
    ports[0].onFrame(snapshotFrame());
    ports[0].onFrame(frame("autonomy.halted", { reason: "x" }));
    await vi.advanceTimersByTimeAsync(SETTLE_MS);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(store.getSnapshot().activeAccountId).toBe(ID);
    // and the same read can be asked for again
    ports[0].onFrame(frame("autonomy.halted", { reason: "y" }));
    await vi.advanceTimersByTimeAsync(SETTLE_MS);
    expect(call).toHaveBeenCalledTimes(2);
  });
});

describe("the gestures", () => {
  it("engages the kill switch on the active account, and nothing else", async () => {
    const { ports, controller, call } = rig();
    call.mockResolvedValue({ lockoutId: "l1" });
    controller.start();
    ports[0].onFrame(snapshotFrame());
    await controller.engageKillSwitch();
    expect(call).toHaveBeenCalledWith("risk_engage_kill_switch", { body: { accountId: ID } });
  });

  it("acknowledges a lockout by the id the core gave", async () => {
    const { ports, controller, call } = rig();
    call.mockResolvedValue({ lockoutId: "l1" });
    controller.start();
    ports[0].onFrame(snapshotFrame());
    await controller.acknowledgeLockout("l1");
    expect(call).toHaveBeenCalledWith("risk_acknowledge", { path: { lockout_id: "l1" }, body: { accountId: ID } });
  });

  it("refuses without an active account, and passes the core's refusal on untouched", async () => {
    const { ports, controller, call } = rig();
    controller.start();
    await expect(controller.engageKillSwitch()).rejects.toThrow(/Aucun compte actif/);
    await expect(controller.acknowledgeLockout("l1")).rejects.toThrow(/Aucun compte actif/);
    expect(call).not.toHaveBeenCalled();

    ports[0].onFrame(snapshotFrame());
    const refusal = new Error("lockout_not_active");
    call.mockRejectedValue(refusal);
    await expect(controller.acknowledgeLockout("l1")).rejects.toBe(refusal);
  });
});
