import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CockpitEvent } from "@/lib/api/generated";
import { CockpitTokenError } from "@/lib/security/cockpit-token";
import {
  BROKEN_ISSUE,
  CockpitSocket,
  REFUSED_ISSUE,
  UNREACHABLE_ISSUE,
  defaultBackoff,
  issueForClose,
  parseFrame,
  type SocketLike,
  type SocketState,
} from "./cockpit-socket";

class FakeSocket implements SocketLike {
  static all: FakeSocket[] = [];

  readyState = 0;

  sent: string[] = [];

  closedWith: number | null = null;

  onopen: SocketLike["onopen"] = null;

  onmessage: SocketLike["onmessage"] = null;

  onclose: SocketLike["onclose"] = null;

  onerror: SocketLike["onerror"] = null;

  constructor(readonly url: string) {
    FakeSocket.all.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(code = 1000): void {
    this.closedWith = code;
    this.readyState = 3;
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.({});
  }

  frame(type: string, payload: object = {}): void {
    this.onmessage?.({ data: JSON.stringify({ type, id: "f", occurredAt: "t", accountId: null, correlationId: null, payload }) });
  }

  closeFromServer(code: number): void {
    this.readyState = 3;
    this.onclose?.({ code });
  }
}

interface Rig {
  socket: CockpitSocket;
  states: Array<[SocketState, string | null]>;
  frames: CockpitEvent[];
  clock: { t: number };
  token: ReturnType<typeof vi.fn>;
  probe: ReturnType<typeof vi.fn>;
}

function rig(overrides: Partial<ConstructorParameters<typeof CockpitSocket>[0]> = {}): Rig {
  const states: Rig["states"] = [];
  const frames: CockpitEvent[] = [];
  const clock = { t: 0 };
  const token = vi.fn(async () => "tok en/1");
  const probe = vi.fn(async () => false);
  const socket = new CockpitSocket({
    url: "ws://core.test/ws",
    getToken: token,
    createSocket: (url) => new FakeSocket(url),
    probe,
    now: () => clock.t,
    onFrame: (frame) => frames.push(frame),
    onState: (state, issue) => states.push([state, issue]),
    ...overrides,
  });
  return { socket, states, frames, clock, token, probe };
}

const last = <T>(items: T[]): T => items[items.length - 1];

/** Move the fake timers and the injected clock together, in steps no longer than the watchdog's period. */
async function pass(r: Rig, ms: number): Promise<void> {
  let left = ms;
  while (left > 0) {
    const step = Math.min(500, left);
    r.clock.t += step;
    await vi.advanceTimersByTimeAsync(step);
    left -= step;
  }
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeSocket.all = [];
});

afterEach(() => {
  vi.useRealTimers();
});

describe("parseFrame", () => {
  it("accepts a frame with a type and an object payload, nothing else", () => {
    expect(parseFrame('{"type":"risk.state_updated","payload":{"a":1}}')).toMatchObject({ type: "risk.state_updated" });
    expect(parseFrame("not json")).toBeNull();
    expect(parseFrame('{"type":"x"}')).toBeNull();
    expect(parseFrame('{"type":1,"payload":{}}')).toBeNull();
    expect(parseFrame('{"type":"x","payload":null}')).toBeNull();
    expect(parseFrame("[1]")).toBeNull();
    expect(parseFrame(42)).toBeNull();
  });
});

describe("the connection", () => {
  it("fetches the token fresh, puts it in the URL encoded, and is connected only once the snapshot is in", async () => {
    const r = rig();
    r.socket.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(r.token).toHaveBeenCalledTimes(1);
    const socket = FakeSocket.all[0];
    expect(socket.url).toBe("ws://core.test/ws?access_token=tok%20en%2F1");
    expect(last(r.states)).toEqual(["connecting", null]);

    socket.open();
    expect(last(r.states)).toEqual(["connecting", null]); // open is not trustworthy yet
    socket.frame("system.snapshot", { accounts: [] });
    expect(last(r.states)).toEqual(["connected", null]);
    socket.frame("system.heartbeat", { seq: 1 });
    expect(r.frames.map((f) => f.type)).toEqual(["system.snapshot", "system.heartbeat"]);
  });

  it("ignores what is not a frame of the contract", async () => {
    const r = rig();
    r.socket.start();
    await vi.advanceTimersByTimeAsync(0);
    const socket = FakeSocket.all[0];
    socket.open();
    socket.onmessage?.({ data: "garbage" });
    socket.onmessage?.({ data: new ArrayBuffer(2) });
    expect(r.frames).toEqual([]);
  });

  it("sends resync and subscribe only while the link is open", async () => {
    const r = rig();
    r.socket.start();
    await vi.advanceTimersByTimeAsync(0);
    const socket = FakeSocket.all[0];
    r.socket.resync();
    expect(socket.sent).toEqual([]);
    socket.open();
    r.socket.resync();
    r.socket.subscribe(["a1"]);
    expect(socket.sent.map((s) => JSON.parse(s))).toEqual([{ type: "resync" }, { type: "subscribe", accountIds: ["a1"] }]);
  });

  it("stops for good: no reconnection, handlers detached, and it can start again", async () => {
    const r = rig();
    r.socket.start();
    await vi.advanceTimersByTimeAsync(0);
    const first = FakeSocket.all[0];
    first.open();
    first.frame("system.snapshot");
    r.socket.stop();
    expect(first.closedWith).toBe(1000);
    expect(last(r.states)).toEqual(["disconnected", null]);
    first.closeFromServer(1006); // a late close of the old socket changes nothing
    await pass(r, 60_000);
    expect(FakeSocket.all).toHaveLength(1);

    r.socket.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(FakeSocket.all).toHaveLength(2);
  });

  it("a stop right after a start (React strict mode) leaves exactly one live socket", async () => {
    const r = rig();
    r.socket.start();
    r.socket.stop();
    r.socket.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(FakeSocket.all).toHaveLength(1);
  });
});

describe("silence", () => {
  async function connected(r: Rig): Promise<FakeSocket> {
    r.socket.start();
    await vi.advanceTimersByTimeAsync(0);
    const socket = FakeSocket.all[FakeSocket.all.length - 1];
    socket.open();
    socket.frame("system.snapshot");
    return socket;
  }

  it("calls a quiet link stale, and a frame revives it", async () => {
    const r = rig();
    const socket = await connected(r);
    await pass(r, 7_000);
    expect(last(r.states)[0]).toBe("connected");
    await pass(r, 2_000);
    expect(last(r.states)[0]).toBe("stale");
    expect(last(r.states)[1]).toMatch(/battement/);
    socket.frame("system.heartbeat");
    expect(last(r.states)).toEqual(["connected", null]);
  });

  it("closes a dead link and comes back", async () => {
    const r = rig();
    const socket = await connected(r);
    await pass(r, 21_000);
    expect(socket.closedWith).toBe(4000);
    expect(last(r.states)).toEqual(["reconnecting", BROKEN_ISSUE]);
    await pass(r, 1_000);
    expect(FakeSocket.all).toHaveLength(2);
    expect(last(r.states)[0]).toBe("reconnecting"); // the second attempt says so until its snapshot arrives
    FakeSocket.all[1].open();
    FakeSocket.all[1].frame("system.snapshot");
    expect(last(r.states)).toEqual(["connected", null]);
  });
});

describe("failures", () => {
  it("says what each close means", () => {
    expect(issueForClose(1008)).toBe(REFUSED_ISSUE);
    expect(issueForClose(1013)).toMatch(/trop lent/);
    expect(issueForClose(1011)).toMatch(/erreur/);
    expect(issueForClose(1006)).toBeNull();
  });

  it("a refusal by the core (1008) is reported as a refusal, and retried", async () => {
    const r = rig();
    r.socket.start();
    await vi.advanceTimersByTimeAsync(0);
    FakeSocket.all[0].closeFromServer(1008);
    await vi.advanceTimersByTimeAsync(0);
    expect(last(r.states)).toEqual(["reconnecting", REFUSED_ISSUE]);
    await pass(r, 1_000);
    expect(FakeSocket.all).toHaveLength(2);
  });

  it("a handshake that fails is told apart: a core that is down, and one that is up but refuses", async () => {
    const down = rig();
    down.socket.start();
    await vi.advanceTimersByTimeAsync(0);
    FakeSocket.all[0].closeFromServer(1006);
    await vi.advanceTimersByTimeAsync(0);
    expect(last(down.states)).toEqual(["reconnecting", UNREACHABLE_ISSUE]);
    down.socket.stop();

    const refusing = rig({ probe: vi.fn(async () => true) });
    refusing.socket.start();
    await vi.advanceTimersByTimeAsync(0);
    FakeSocket.all[FakeSocket.all.length - 1].closeFromServer(1006);
    await vi.advanceTimersByTimeAsync(0);
    expect(last(refusing.states)).toEqual(["reconnecting", REFUSED_ISSUE]);
  });

  it("backs off 1 s, 2 s, 4 s … and starts over once a snapshot has arrived", async () => {
    const r = rig();
    r.socket.start();
    await vi.advanceTimersByTimeAsync(0);
    const waits: number[] = [];
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const count = FakeSocket.all.length;
      FakeSocket.all[count - 1].closeFromServer(1006);
      await vi.advanceTimersByTimeAsync(0);
      let waited = 0;
      while (FakeSocket.all.length === count) {
        await pass(r, 500);
        waited += 500;
      }
      waits.push(waited);
    }
    expect(waits).toEqual([1_000, 2_000, 4_000]);

    const live = FakeSocket.all[FakeSocket.all.length - 1];
    live.open();
    live.frame("system.snapshot");
    live.closeFromServer(1006);
    await vi.advanceTimersByTimeAsync(0);
    const count = FakeSocket.all.length;
    await pass(r, 1_000);
    expect(FakeSocket.all).toHaveLength(count + 1); // back to the first delay
  });

  it("caps the delay", () => {
    expect([0, 1, 2, 3, 4, 5, 9].map(defaultBackoff)).toEqual([1_000, 2_000, 4_000, 8_000, 10_000, 10_000, 10_000]);
  });

  it("reports a token the Next server could not hand over, in its own words, and retries", async () => {
    const token = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new CockpitTokenError("Jeton du cockpit absent : ..."))
      .mockResolvedValue("tok");
    const r = rig({ getToken: token });
    r.socket.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(last(r.states)).toEqual(["reconnecting", "Jeton du cockpit absent : ..."]);
    expect(FakeSocket.all).toHaveLength(0);
    await pass(r, 1_000);
    expect(FakeSocket.all).toHaveLength(1);
  });
});
