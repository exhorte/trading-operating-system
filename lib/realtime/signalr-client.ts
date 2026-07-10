/**
 * SignalR realtime client — the production dashboard transport (ADR 0005/0009).
 *
 * Connects to the ASP.NET Core CockpitHub, hydrates from GetSnapshot, then
 * applies "event" envelopes already TRANSLATED server-side by the .NET
 * gateway (unlike LiveRealtimeClient, which translated in the browser as the
 * Phase 05 prototype shortcut). The TS engines still run client-side in this
 * slice: real candles → ICT/SMC market context, account/positions → risk
 * state (engine port to C# is deferred).
 *
 * Read-only observe path: never sends anything but the snapshot request.
 */

import {
  HubConnection,
  HubConnectionBuilder,
  HubConnectionState,
} from "@microsoft/signalr";
import { analyzeMarketContext, DEFAULT_SESSION_WINDOWS } from "@/lib/analysis";
import { sessionEnabled, sessionForTimestamp } from "@/lib/analysis/sessions";
import { defaultRiskPolicy, evaluateRiskState } from "@/lib/risk";
import {
  toMarketContextReadModel,
  toRiskStatusReadModel,
} from "@/lib/contracts/projections";
import type { Envelope } from "@/lib/contracts/envelope";
import type {
  AgentHeartbeatPayload,
  MarketCandlePayload,
  MarketTickPayload,
} from "@/lib/contracts/events";
import type {
  AccountSummary,
  AgentStatus,
  Position,
} from "@/lib/contracts/snapshots";
import type { Candle } from "@/lib/domain/market";
import type { RealtimeClient } from "./client";
import type { CockpitStore } from "./store";

const WATCHDOG_INTERVAL_MS = 2_000;
const HEARTBEAT_STALE_AFTER_MS = 8_000;
const CONTEXT_DEBOUNCE_MS = 200;
const MAX_CANDLES = 300;

/** Shape returned by CockpitHub.GetSnapshot (C# CockpitSnapshotDto, camelCase). */
interface HubSnapshot {
  account: AccountSummary | null;
  positions: Position[];
  agents: AgentStatus[];
  candles: Candle[];
}

export class SignalRRealtimeClient implements RealtimeClient {
  private connection: HubConnection | null = null;

  private stopped = false;

  private candles = new Map<string, Candle>();

  private lastBid: number | null = null;

  private lastAsk: number | null = null;

  private baselineBalance: number | null = null;

  private baselineEquity: number | null = null;

  private symbol = "XAUUSDm";

  private timeframe = "M15";

  private watchdog: ReturnType<typeof setInterval> | null = null;

  private contextTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(
    private readonly store: CockpitStore,
    private readonly hubUrl: string,
  ) {}

  start(): void {
    this.stopped = false;
    this.store.hydrate({ environment: "demo" });
    this.store.setConnectionState("connecting");

    const connection = new HubConnectionBuilder()
      .withUrl(this.hubUrl)
      .withAutomaticReconnect()
      .build();
    this.connection = connection;

    connection.on("event", (envelope: Envelope) => this.onEvent(envelope));
    connection.onreconnecting(() => this.store.setConnectionState("reconnecting"));
    connection.onreconnected(() => {
      this.store.setConnectionState("connected");
      void this.hydrateFromSnapshot();
    });
    connection.onclose(() => {
      if (!this.stopped) {
        this.store.setConnectionState("disconnected");
      }
    });

    void connection
      .start()
      .then(() => {
        this.store.setConnectionState("connected");
        this.store.hydrate({ lastHeartbeatAt: new Date().toISOString() });
        this.startWatchdog();
        return this.hydrateFromSnapshot();
      })
      .catch(() => {
        // withAutomaticReconnect only covers established connections; retry
        // the initial connect ourselves.
        if (!this.stopped) {
          this.store.setConnectionState("reconnecting");
          setTimeout(() => {
            if (!this.stopped) {
              this.stop();
              this.start();
            }
          }, 3_000);
        }
      });
  }

  stop(): void {
    this.stopped = true;
    if (this.watchdog) {
      clearInterval(this.watchdog);
      this.watchdog = null;
    }
    if (this.contextTimer) {
      clearTimeout(this.contextTimer);
      this.contextTimer = null;
    }
    if (this.connection) {
      const connection = this.connection;
      this.connection = null;
      if (connection.state !== HubConnectionState.Disconnected) {
        void connection.stop();
      }
    }
  }

  /** Snapshot on connect/reconnect, then the event stream (documented pattern). */
  private async hydrateFromSnapshot(): Promise<void> {
    if (!this.connection) {
      return;
    }
    const snapshot = await this.connection.invoke<HubSnapshot>("GetSnapshot");
    // Reset the session baseline on every resync, like the live client.
    if (snapshot.account) {
      this.baselineBalance = snapshot.account.balance;
      this.baselineEquity = snapshot.account.equity;
    }
    this.candles.clear();
    for (const candle of snapshot.candles) {
      this.candles.set(candle.openTime, candle);
      this.symbol = candle.symbol;
      this.timeframe = candle.timeframe;
    }
    this.store.hydrate({
      account: snapshot.account,
      positions: snapshot.positions,
      agents: snapshot.agents,
    });
    this.scheduleContextRecompute();
    this.recomputeRisk();
  }

  private onEvent(envelope: Envelope): void {
    switch (envelope.type) {
      case "market.tick": {
        const { bid, ask } = envelope.payload as MarketTickPayload;
        this.lastBid = bid;
        this.lastAsk = ask;
        this.store.apply(envelope);
        break;
      }
      case "market.candle.closed": {
        const { candle } = envelope.payload as MarketCandlePayload;
        this.symbol = candle.symbol;
        this.timeframe = candle.timeframe;
        this.candles.set(candle.openTime, candle);
        if (this.candles.size > MAX_CANDLES) {
          const oldest = [...this.candles.keys()].sort()[0];
          this.candles.delete(oldest);
        }
        this.scheduleContextRecompute();
        break;
      }
      case "agent.snapshot.account": {
        this.store.apply(envelope);
        const account = this.store.getSnapshot().account;
        if (account && this.baselineBalance === null) {
          this.baselineBalance = account.balance;
          this.baselineEquity = account.equity;
        }
        this.recomputeRisk();
        break;
      }
      case "agent.snapshot.positions": {
        this.store.apply(envelope);
        this.recomputeRisk();
        break;
      }
      case "agent.heartbeat": {
        const payload = envelope.payload as AgentHeartbeatPayload;
        this.store.setConnectionState("connected");
        this.store.apply(envelope);
        void payload;
        break;
      }
      default:
        this.store.apply(envelope);
        break;
    }
  }

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
    const candles = [...this.candles.values()].sort(
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

  /** Same observe-mode risk computation as the live client: session baseline,
   *  real spread, honest null trade counts. */
  private recomputeRisk(): void {
    const { account, positions } = this.store.getSnapshot();
    if (!account || this.baselineBalance === null || this.baselineEquity === null) {
      return;
    }
    const policy = defaultRiskPolicy(account.accountId);
    const spreadPoints =
      this.lastAsk !== null && this.lastBid !== null
        ? Math.round((this.lastAsk - this.lastBid) / 0.01)
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
      }
    }, WATCHDOG_INTERVAL_MS);
  }
}
