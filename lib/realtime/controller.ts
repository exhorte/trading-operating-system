/**
 * Puts the stream, the store and the API together — the cockpit's only live connection, with no screen in it.
 *
 *   socket ──frame──▶ store.apply ──effects──▶ read again (REST) / ask for a fresh snapshot
 *
 * A frame the store cannot apply by itself comes back as an *effect*; this is where it is carried out, a little late on
 * purpose: a connection or a burst of orders produces several events within a few milliseconds, and one read after the burst
 * says the same thing as one read after each.
 *
 * It also holds the two gestures the shell offers from every screen — the kill switch and its acknowledgement — and nothing
 * else: they are requests to the core, which decides. Whether the account is locked is what the core reports back through the
 * stream, not what this module assumes it did.
 */

import { call as defaultCall } from "@/lib/api/client";
import { CockpitSocket, type SocketOptions, type SocketState } from "@/lib/websocket/cockpit-socket";
import type { CockpitStore, Effect, LinkState } from "./store";

/** How long to wait for a burst to finish before reading again. */
export const SETTLE_MS = 250;

export interface SocketPort {
  start(): void;
  stop(): void;
  resync(): void;
}

export interface ControllerDeps {
  call?: typeof defaultCall;
  createSocket?: (options: Pick<SocketOptions, "onFrame" | "onState">) => SocketPort;
  /** Failures of the follow-up reads are not the trader's to fix: they are logged and the next event or snapshot corrects them. */
  warn?: (message: string, error: unknown) => void;
}

const LINK_OF: Record<SocketState, LinkState> = {
  connecting: "connecting",
  connected: "connected",
  reconnecting: "reconnecting",
  stale: "stale",
  disconnected: "disconnected",
};

export class CockpitController {
  private socket: SocketPort | null = null;

  private timers = new Map<string, ReturnType<typeof setTimeout>>();

  private readonly call: typeof defaultCall;

  private readonly warn: (message: string, error: unknown) => void;

  constructor(
    private readonly store: CockpitStore,
    private readonly deps: ControllerDeps = {},
  ) {
    this.call = deps.call ?? defaultCall;
    this.warn = deps.warn ?? ((message, error) => console.warn(message, error));
  }

  start(): void {
    if (this.socket !== null) {
      return;
    }
    const options = {
      onFrame: (frame: Parameters<CockpitStore["apply"]>[0]) => this.run(this.store.apply(frame)),
      onState: (state: SocketState, issue: string | null) => this.store.setLink(LINK_OF[state], issue),
    };
    this.socket = this.deps.createSocket ? this.deps.createSocket(options) : new CockpitSocket(options);
    this.socket.start();
  }

  stop(): void {
    this.socket?.stop();
    this.socket = null;
    for (const timer of this.timers.values()) {
      clearTimeout(timer);
    }
    this.timers.clear();
  }

  // ------------------------------------------------------------------------------------------------ the gestures

  /**
   * T02a: the manual kill switch. Locks the account in the core's ledger; it never closes anything — positions are closed in
   * MT5 by the trader. Idempotent in the core: engaged twice is engaged once. Rejects with the core's own refusal.
   */
  async engageKillSwitch(): Promise<void> {
    const accountId = this.store.getSnapshot().activeAccountId;
    if (accountId === null) {
      throw new Error("Aucun compte actif : rien à verrouiller.");
    }
    await this.call("risk_engage_kill_switch", { body: { accountId } });
  }

  /** The trader's own record of having taken note of an untimed lockout — the only way one is ever lifted. */
  async acknowledgeLockout(lockoutId: string): Promise<void> {
    const accountId = this.store.getSnapshot().activeAccountId;
    if (accountId === null) {
      throw new Error("Aucun compte actif.");
    }
    await this.call("risk_acknowledge", { path: { lockout_id: lockoutId }, body: { accountId } });
  }

  // ------------------------------------------------------------------------------------------------ the effects

  private run(effects: Effect[]): void {
    for (const effect of effects) {
      switch (effect.kind) {
        case "resync":
          this.later("resync", () => this.socket?.resync());
          break;
        case "refresh-commands":
          this.later(`commands:${effect.accountId}`, () => this.refreshCommands(effect.accountId));
          break;
        case "refresh-autonomy":
          this.later("autonomy", () => this.refreshAutonomy());
          break;
      }
    }
  }

  /** One timer per kind of read: asking again while one is waiting does not push it back, it joins it. */
  private later(key: string, work: () => void | Promise<void>): void {
    if (this.timers.has(key)) {
      return;
    }
    this.timers.set(
      key,
      setTimeout(() => {
        this.timers.delete(key);
        void Promise.resolve(work()).catch((error: unknown) => this.warn(`cockpit: ${key} could not be read`, error));
      }, SETTLE_MS),
    );
  }

  private async refreshCommands(accountId: string): Promise<void> {
    const commands = await this.call("execution_commands", { query: { accountId, limit: 20 } });
    this.store.setCommands(accountId, commands);
  }

  private async refreshAutonomy(): Promise<void> {
    this.store.setAutonomy(await this.call("autonomy_state"));
  }
}
