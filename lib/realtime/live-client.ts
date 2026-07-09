/**
 * Live realtime client for the observe-only MT5 prototype.
 *
 * Connects to the local Python producer (tools/mt5-observer) over a WebSocket,
 * translates lean MT5 messages into the CockpitStore, and runs the Phase 04
 * ICT/SMC engine on the real candle stream. It is READ-ONLY: it never sends a
 * command. Same seam as MockRealtimeClient, so components never change.
 *
 * Prototype scope: the lean→internal translation runs here in the browser (see
 * ADR 0007); the definitive server-side .NET gateway replaces it later.
 */

import { analyzeMarketContext, DEFAULT_SESSION_WINDOWS } from "@/lib/analysis";
import { sessionEnabled, sessionForTimestamp } from "@/lib/analysis/sessions";
import { defaultRiskPolicy, evaluateRiskState } from "@/lib/risk";
import {
  toMarketContextReadModel,
  toRiskStatusReadModel,
} from "@/lib/contracts/projections";
import type {
  Mt5AccountSnapshotMessage,
  Mt5CandleMessage,
  Mt5HeartbeatMessage,
  Mt5HelloMessage,
  Mt5InboundMessage,
  Mt5PositionsSnapshotMessage,
  Mt5TickMessage,
} from "@/lib/contracts/mt5-wire";
import type { Candle } from "@/lib/domain/market";
import {
  toAccountSummary,
  toAgentStatus,
  toCandle,
  toPositions,
} from "./mt5-translate";
import type { RealtimeClient } from "./client";
import type { CockpitStore } from "./store";

const RECONNECT_DELAY_MS = 3_000;
const WATCHDOG_INTERVAL_MS = 2_000;
const HEARTBEAT_STALE_AFTER_MS = 8_000;
const CONTEXT_DEBOUNCE_MS = 200;
const MAX_CANDLES = 300;

export class LiveRealtimeClient implements RealtimeClient {
  private socket: WebSocket | null = null;

  private stopped = false;

  private hello: Mt5HelloMessage | null = null;

  private lastPrice: number | null = null;

  private lastAsk: number | null = null;

  /** Session baseline captured at connect for daily-loss / drawdown in live. */
  private baselineBalance: number | null = null;

  private baselineEquity: number | null = null;

  private symbol = "XAUUSDm";

  private timeframe = "M15";

  /** Real candles keyed by epoch open time; fed to the ICT/SMC engine. */
  private candles = new Map<number, Candle>();

  private watchdog: ReturnType<typeof setInterval> | null = null;

  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  private contextTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly store: CockpitStore,
    private readonly url: string,
  ) {}

  start(): void {
    this.stopped = false;
    // In live mode the badge must read DEMO, never MOCK — set it before connect.
    this.store.hydrate({ environment: "demo" });
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.clearTimer(this.reconnectTimer);
    this.clearTimer(this.contextTimer);
    if (this.watchdog) {
      clearInterval(this.watchdog);
      this.watchdog = null;
    }
    if (this.socket) {
      this.socket.onopen = null;
      this.socket.onmessage = null;
      this.socket.onclose = null;
      this.socket.onerror = null;
      this.socket.close();
      this.socket = null;
    }
  }

  private connect(): void {
    if (this.stopped || typeof WebSocket === "undefined") {
      return;
    }
    // Recapture the session baseline on every (re)connect.
    this.baselineBalance = null;
    this.baselineEquity = null;
    this.store.setConnectionState("connecting");
    const socket = new WebSocket(this.url);
    this.socket = socket;

    socket.onopen = () => {
      this.store.setConnectionState("connected");
      this.store.hydrate({ lastHeartbeatAt: new Date().toISOString() });
      this.startWatchdog();
    };
    socket.onmessage = (event) => this.onMessage(event.data);
    socket.onclose = () => this.scheduleReconnect();
    socket.onerror = () => socket.close();
  }

  private scheduleReconnect(): void {
    if (this.stopped) {
      return;
    }
    this.store.setConnectionState("reconnecting");
    this.markAgentsDisconnected();
    this.clearTimer(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => this.connect(), RECONNECT_DELAY_MS);
  }

  private onMessage(raw: unknown): void {
    if (typeof raw !== "string") {
      return;
    }
    let msg: Mt5InboundMessage;
    try {
      msg = JSON.parse(raw) as Mt5InboundMessage;
    } catch {
      return;
    }

    switch (msg.type) {
      case "agent.hello":
        this.onHello(msg);
        break;
      case "account.snapshot":
        this.onAccount(msg);
        break;
      case "positions.snapshot":
        this.onPositions(msg);
        break;
      case "market.tick":
        this.onTick(msg);
        break;
      case "market.candle":
        this.onCandle(msg);
        break;
      case "agent.heartbeat":
        this.onHeartbeat(msg);
        break;
      default:
        // ack/report/error are not used in the observe prototype.
        break;
    }
  }

  private onHello(msg: Mt5HelloMessage): void {
    this.hello = msg;
    this.symbol = msg.symbol;
    this.store.hydrate({ environment: "demo", agents: [toAgentStatus(msg)] });
  }

  private onAccount(msg: Mt5AccountSnapshotMessage): void {
    if (this.baselineBalance === null) {
      this.baselineBalance = msg.balance;
      this.baselineEquity = msg.equity;
    }
    this.store.hydrate({ account: toAccountSummary(msg, this.hello) });
    this.recomputeRisk();
  }

  private onPositions(msg: Mt5PositionsSnapshotMessage): void {
    this.store.hydrate({ positions: toPositions(msg, this.lastPrice) });
    this.recomputeRisk();
  }

  /** Compute risk from real account + positions + spread + session (observe:
   *  trades/consecutive losses are unknown → null → honest "n/a" gates). */
  private recomputeRisk(): void {
    const { account, positions } = this.store.getSnapshot();
    if (!account || this.baselineBalance === null || this.baselineEquity === null) {
      return;
    }
    const policy = defaultRiskPolicy(account.accountId);
    const spreadPoints =
      this.lastAsk !== null && this.lastPrice !== null
        ? Math.round((this.lastAsk - this.lastPrice) / 0.01)
        : null;
    const nowIso = new Date().toISOString();
    const session = sessionForTimestamp(nowIso, DEFAULT_SESSION_WINDOWS);
    const state = evaluateRiskState({
      policy,
      initialBalance: this.baselineBalance,
      dayStartEquity: this.baselineEquity,
      equity: account.equity,
      balance: account.balance,
      positions: positions.map((p) => ({
        symbol: p.symbol,
        entryPrice: p.entryPrice,
        stopLoss: p.stopLoss,
        volume: p.volume,
      })),
      tradesToday: null,
      consecutiveLosses: null,
      spreadPoints,
      session,
      sessionTradingEnabled: sessionEnabled(session, DEFAULT_SESSION_WINDOWS),
      now: nowIso,
    });
    this.store.hydrate({ risk: toRiskStatusReadModel(state, policy) });
  }

  private onTick(msg: Mt5TickMessage): void {
    this.lastPrice = msg.bid;
    this.lastAsk = msg.ask;
    // Cosmetic: keep current price fresh; real P&L arrives on the next snapshot.
    const positions = this.store.getSnapshot().positions.map((p) =>
      p.symbol === msg.symbol ? { ...p, currentPrice: msg.bid } : p,
    );
    this.store.hydrate({ positions });
  }

  private onCandle(msg: Mt5CandleMessage): void {
    this.timeframe = msg.timeframe;
    this.candles.set(msg.openTime, toCandle(msg));
    if (this.candles.size > MAX_CANDLES) {
      const oldest = Math.min(...this.candles.keys());
      this.candles.delete(oldest);
    }
    this.scheduleContextRecompute();
  }

  private onHeartbeat(msg: Mt5HeartbeatMessage): void {
    const nowIso = new Date().toISOString();
    this.store.setConnectionState("connected");
    this.store.hydrate({
      lastHeartbeatAt: nowIso,
      agents: this.store.getSnapshot().agents.map((agent) =>
        agent.agentId === msg.agentId
          ? { ...agent, state: "connected", latencyMs: msg.latencyMs, lastHeartbeatAt: nowIso }
          : agent,
      ),
    });
  }

  /** Coalesce bursts of candle messages (e.g. the initial backfill) into one run. */
  private scheduleContextRecompute(): void {
    if (this.contextTimer) {
      return;
    }
    this.contextTimer = setTimeout(() => {
      this.contextTimer = null;
      this.recomputeContext();
    }, CONTEXT_DEBOUNCE_MS);
  }

  private recomputeContext(): void {
    const candles = Array.from(this.candles.values()).sort(
      (a, b) => Date.parse(a.openTime) - Date.parse(b.openTime),
    );
    if (candles.length === 0) {
      return;
    }
    const state = analyzeMarketContext({
      symbol: this.symbol,
      timeframe: this.timeframe as Candle["timeframe"],
      candles,
    });
    this.store.hydrate({ marketContext: toMarketContextReadModel(state) });
  }

  private startWatchdog(): void {
    if (this.watchdog) {
      return;
    }
    this.watchdog = setInterval(() => {
      const { connection, lastHeartbeatAt } = this.store.getSnapshot();
      if (connection !== "connected" || !lastHeartbeatAt) {
        return;
      }
      if (Date.now() - Date.parse(lastHeartbeatAt) > HEARTBEAT_STALE_AFTER_MS) {
        this.store.setConnectionState("stale");
        this.markAgentsDisconnected();
      }
    }, WATCHDOG_INTERVAL_MS);
  }

  private markAgentsDisconnected(): void {
    this.store.hydrate({
      agents: this.store.getSnapshot().agents.map((agent) => ({
        ...agent,
        state: "disconnected",
      })),
    });
  }

  private clearTimer(timer: ReturnType<typeof setTimeout> | null): void {
    if (timer) {
      clearTimeout(timer);
    }
  }
}
