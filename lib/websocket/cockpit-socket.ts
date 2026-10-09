/**
 * The cockpit's live stream: one WebSocket to the core's `/ws`, kept alive.
 *
 * Transport only — it knows how to connect, how to tell a dead link from a quiet one, how to come back, and nothing about what
 * a frame means (that is the store's business). The contract it speaks is the core's (`CockpitHub`):
 *
 *   - the **first** frame of every connection is `system.snapshot`, the whole state; so a client that connects or reconnects
 *     never has to guess what it missed. The link is called *connected* only once that frame has arrived: a socket that is
 *     open but has delivered nothing is not a cockpit that can be trusted;
 *   - every other frame is `{type, id, occurredAt, accountId, correlationId, payload}`;
 *   - the client may send `{"type": "resync"}` to be given a fresh snapshot (used after an event the store cannot apply by
 *     itself) and `{"type": "subscribe", "accountIds": [...]}` to narrow the stream;
 *   - the core closes with 1008 (access refused: token or origin), 1013 (this client was too slow: come back and resync) or
 *     1011 (a fault on its side).
 *
 * The token rides in the query string (`access_token`) because a browser WebSocket cannot set headers; the core therefore never
 * logs a query string, and this module never puts the URL in a message. It is fetched fresh on every attempt: a token changed
 * in `.env` is picked up without reloading the tab.
 *
 * Silence is information. The core beats every 2 s, so a link that has said nothing for `staleAfterMs` is reported `stale`
 * (the figures on screen are old) and one that has said nothing for `deadAfterMs` is closed and re-opened.
 */

import { coreBaseUrl, webSocketUrl } from "@/lib/api/client";
import type { CockpitEvent } from "@/lib/api/generated";
import { fetchCockpitToken, isCockpitTokenError } from "@/lib/security/cockpit-token";

export type SocketState = "connecting" | "connected" | "reconnecting" | "stale" | "disconnected";

/** What the stream needs of a WebSocket — and what a test can fake. */
export interface SocketLike {
  readyState: number;
  send(data: string): void;
  close(code?: number): void;
  onopen: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: { code: number }) => void) | null;
  onerror: ((event: unknown) => void) | null;
}

const OPEN = 1;

export interface SocketOptions {
  onFrame: (frame: CockpitEvent) => void;
  /** The link's state, and in words the trader can act on why it is not `connected` (null when there is nothing to say). */
  onState: (state: SocketState, issue: string | null) => void;
  url?: string;
  getToken?: () => Promise<string>;
  createSocket?: (url: string) => SocketLike;
  /** Whether the core answers at all — told apart from "answers, but refuses us" when a handshake fails. */
  probe?: () => Promise<boolean>;
  now?: () => number;
  staleAfterMs?: number;
  deadAfterMs?: number;
  /** Delay before the n-th consecutive reconnection attempt (0-based). */
  backoffMs?: (attempt: number) => number;
}

export const STALE_AFTER_MS = 8_000;
export const DEAD_AFTER_MS = 20_000;
const WATCHDOG_MS = 1_000;

export function defaultBackoff(attempt: number): number {
  return Math.min(10_000, 1_000 * 2 ** attempt);
}

export const UNREACHABLE_ISSUE =
  "Le cœur ne répond pas. Est-il démarré ? — python -m trading_os serve, ou scripts/start.ps1.";
export const REFUSED_ISSUE =
  "Le cœur tourne mais refuse l'accès : le cockpit et le cœur n'ont pas le même TRADINGOS_COCKPIT_TOKEN " +
  "(ou l'origine de cette page n'est pas autorisée). Relance le cœur après avoir corrigé 04_code/.env.";

export const BROKEN_ISSUE = "La liaison avec le cœur s'est interrompue : reconnexion.";

/** The words for a close code. */
export function issueForClose(code: number): string | null {
  switch (code) {
    case 1008:
      return REFUSED_ISSUE;
    case 1013:
      return "Le cockpit n'a pas suivi le flux du cœur (trop lent) : reconnexion et resynchronisation.";
    case 1011:
      return "Le cœur a rencontré une erreur sur ce flux : reconnexion.";
    default:
      return null;
  }
}

/** A frame as the core sends it. Anything that is not an object with a type and a payload is not one. */
export function parseFrame(data: unknown): CockpitEvent | null {
  if (typeof data !== "string") {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== "object") {
    return null;
  }
  const frame = parsed as { type?: unknown; payload?: unknown };
  if (typeof frame.type !== "string" || frame.payload === null || typeof frame.payload !== "object") {
    return null;
  }
  return parsed as CockpitEvent;
}

async function defaultProbe(): Promise<boolean> {
  try {
    const res = await fetch(`${coreBaseUrl()}/api/system/health`, { cache: "no-store", credentials: "omit" });
    return res.ok;
  } catch {
    return false;
  }
}

export class CockpitSocket {
  private socket: SocketLike | null = null;

  private stopped = true;

  private opened = false;

  private attempt = 0;

  private lastFrameAtMs = 0;

  private state: SocketState = "disconnected";

  private retry: ReturnType<typeof setTimeout> | null = null;

  private watchdog: ReturnType<typeof setInterval> | null = null;

  /** Bumped on every (re)connection and every stop, so a late callback of an earlier socket can tell it is no longer current. */
  private generation = 0;

  private readonly url: () => string;

  private readonly getToken: () => Promise<string>;

  private readonly createSocket: (url: string) => SocketLike;

  private readonly probe: () => Promise<boolean>;

  private readonly now: () => number;

  private readonly staleAfterMs: number;

  private readonly deadAfterMs: number;

  private readonly backoff: (attempt: number) => number;

  constructor(private readonly options: SocketOptions) {
    this.url = () => options.url ?? webSocketUrl();
    this.getToken = options.getToken ?? fetchCockpitToken;
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url) as unknown as SocketLike);
    this.probe = options.probe ?? defaultProbe;
    this.now = options.now ?? Date.now;
    this.staleAfterMs = options.staleAfterMs ?? STALE_AFTER_MS;
    this.deadAfterMs = options.deadAfterMs ?? DEAD_AFTER_MS;
    this.backoff = options.backoffMs ?? defaultBackoff;
  }

  start(): void {
    if (!this.stopped) {
      return;
    }
    this.stopped = false;
    this.attempt = 0;
    void this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.generation += 1;
    if (this.retry !== null) {
      clearTimeout(this.retry);
      this.retry = null;
    }
    this.stopWatchdog();
    const socket = this.socket;
    this.socket = null;
    if (socket !== null) {
      socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null;
      socket.close(1000);
    }
    this.setState("disconnected", null);
  }

  /** Ask the core for a fresh snapshot. A no-op when the link is not up: a reconnection starts with one anyway. */
  resync(): void {
    this.send({ type: "resync" });
  }

  /** Narrow the stream to some accounts (the core answers with a fresh, narrowed snapshot). `null` = every account. */
  subscribe(accountIds: string[] | null): void {
    this.send({ type: "subscribe", accountIds });
  }

  private send(message: Record<string, unknown>): void {
    if (this.socket !== null && this.socket.readyState === OPEN) {
      this.socket.send(JSON.stringify(message));
    }
  }

  private setState(state: SocketState, issue: string | null): void {
    this.state = state;
    this.options.onState(state, issue);
  }

  private async connect(): Promise<void> {
    const generation = ++this.generation;
    this.opened = false;
    this.setState(this.attempt === 0 ? "connecting" : "reconnecting", null);

    let token: string;
    try {
      token = await this.getToken();
    } catch (error) {
      if (generation !== this.generation) {
        return;
      }
      // The Next server could not hand the token over: say so in its own words, then try again.
      this.setState(
        "reconnecting",
        isCockpitTokenError(error) ? error.message : "Jeton du cockpit illisible : le serveur du cockpit ne répond pas.",
      );
      this.scheduleRetry();
      return;
    }
    if (generation !== this.generation) {
      return;
    }

    const base = this.url();
    const socket = this.createSocket(`${base}?access_token=${encodeURIComponent(token)}`);
    this.socket = socket;
    socket.onopen = () => {
      if (generation === this.generation) {
        this.opened = true;
        this.lastFrameAtMs = this.now();
        this.startWatchdog();
      }
    };
    socket.onmessage = (event) => {
      if (generation !== this.generation) {
        return;
      }
      const frame = parseFrame(event.data);
      if (frame === null) {
        return; // not a frame of this contract: ignored, never fatal
      }
      this.lastFrameAtMs = this.now();
      const isSnapshot = frame.type === "system.snapshot";
      if (isSnapshot) {
        this.attempt = 0; // a connection that delivers its snapshot has worked: the next failure starts the backoff over
      }
      if (this.state !== "connected" && (isSnapshot || this.state === "stale")) {
        this.setState("connected", null); // the snapshot makes the link trustworthy; any frame revives a stale one
      }
      this.options.onFrame(frame);
    };
    socket.onerror = () => {
      // A browser says nothing about why: the close that follows carries what there is.
    };
    socket.onclose = (event) => {
      if (generation !== this.generation) {
        return;
      }
      this.socket = null;
      this.stopWatchdog();
      void this.afterClose(generation, event.code);
    };
  }

  private async afterClose(generation: number, code: number): Promise<void> {
    if (this.stopped) {
      return;
    }
    let issue = issueForClose(code);
    if (issue === null) {
      // No word from the core: a link that was up and broke, or a handshake it never accepted — and then, is it even there?
      issue = this.opened ? BROKEN_ISSUE : (await this.probe()) ? REFUSED_ISSUE : UNREACHABLE_ISSUE;
    }
    if (this.stopped || generation !== this.generation) {
      return;
    }
    this.setState("reconnecting", issue);
    this.scheduleRetry();
  }

  private scheduleRetry(): void {
    if (this.stopped || this.retry !== null) {
      return;
    }
    const delay = this.backoff(this.attempt);
    this.attempt += 1;
    this.retry = setTimeout(() => {
      this.retry = null;
      if (!this.stopped) {
        void this.connect();
      }
    }, delay);
  }

  private startWatchdog(): void {
    if (this.watchdog !== null) {
      return;
    }
    this.watchdog = setInterval(() => {
      if (this.stopped || this.socket === null) {
        return;
      }
      const silence = this.now() - this.lastFrameAtMs;
      if (silence > this.deadAfterMs) {
        // Nothing for this long: the link is dead whatever the socket believes. Let go of it and take the retry path.
        const socket = this.socket;
        this.socket = null;
        socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null;
        socket.close(4000);
        this.stopWatchdog();
        void this.afterClose(this.generation, 4000);
      } else if (silence > this.staleAfterMs && this.state === "connected") {
        this.setState("stale", "Aucun battement du cœur depuis plusieurs secondes : les chiffres ne sont plus frais.");
      }
    }, WATCHDOG_MS);
  }

  private stopWatchdog(): void {
    if (this.watchdog !== null) {
      clearInterval(this.watchdog);
      this.watchdog = null;
    }
  }
}
