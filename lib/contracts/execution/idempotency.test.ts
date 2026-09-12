import { describe, expect, it, vi } from "vitest";
import { recordOrReplay } from "./idempotency";

describe("recordOrReplay", () => {
  it("executes and records on first sight of a commandId", () => {
    const execute = vi.fn(() => ({ status: "accepted" }));
    const { attempt, nextStore } = recordOrReplay(new Map(), "cmd-1", execute);

    expect(execute).toHaveBeenCalledTimes(1);
    expect(attempt).toEqual({ result: { status: "accepted" }, wasReplay: false });
    expect(nextStore.get("cmd-1")).toEqual({ status: "accepted" });
  });

  it("a replayed commandId returns the PREVIOUS result and never re-executes", () => {
    const store = new Map([["cmd-1", { status: "accepted", brokerPositionId: "78910" }]]);
    const execute = vi.fn(() => ({ status: "accepted", brokerPositionId: "SECOND_POSITION" }));

    const { attempt, nextStore } = recordOrReplay(store, "cmd-1", execute);

    expect(execute).not.toHaveBeenCalled();
    expect(attempt).toEqual({
      result: { status: "accepted", brokerPositionId: "78910" },
      wasReplay: true,
    });
    // Never a second position: the stored result is untouched by the replay.
    expect(nextStore.get("cmd-1")).toEqual({ status: "accepted", brokerPositionId: "78910" });
  });

  it("never mutates the input store — pure", () => {
    const store = new Map([["cmd-1", "first"]]);
    recordOrReplay(store, "cmd-2", () => "second");

    expect(store.size).toBe(1);
    expect(store.has("cmd-2")).toBe(false);
  });

  it("different commandIds are tracked independently", () => {
    let store = new Map<string, string>();
    ({ nextStore: store } = recordOrReplay(store, "cmd-1", () => "result-1"));
    const { attempt, nextStore } = recordOrReplay(store, "cmd-2", () => "result-2");

    expect(attempt).toEqual({ result: "result-2", wasReplay: false });
    expect(nextStore.get("cmd-1")).toBe("result-1");
    expect(nextStore.get("cmd-2")).toBe("result-2");
  });
});
