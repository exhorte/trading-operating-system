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
import { defaultRiskPolicy, evaluateRiskState, evaluateSignalRisk } from "@/lib/risk";
import { buildPlaceOrderCommand } from "@/lib/execution/command-builder";
import { mockStrategySignal } from "@/lib/mock/signals";
import { makeEnvelope } from "@/lib/mock/envelope";
import {
  toMarketContextReadModel,
  toRiskDecisionView,
  toRiskStatusReadModel,
  toStrategySignalReadModel,
} from "@/lib/contracts/projections";
import type { Envelope } from "@/lib/contracts/envelope";
import type {
  AgentHeartbeatPayload,
  MarketCandlePayload,
  MarketTickPayload,
  RiskDecisionMadePayload,
  SignalCreatedPayload,
} from "@/lib/contracts/events";
import type { CommandAckPayload } from "@/lib/contracts/commands";
import type {
  AccountSummary,
  AgentStatus,
  Position,
} from "@/lib/contracts/snapshots";
import type { Candle } from "@/lib/domain/market";
import type { MarketContextState } from "@/lib/domain/analysis";
import type { PlaceOrderCommand } from "@/lib/domain/execution";
import type { RiskPolicy, RiskState } from "@/lib/domain/risk";
import type { RealtimeClient } from "./client";
import type { CockpitStore } from "./store";

const WATCHDOG_INTERVAL_MS = 2_000;
const HEARTBEAT_STALE_AFTER_MS = 8_000;
const CONTEXT_DEBOUNCE_MS = 200;
const MAX_CANDLES = 300;
/** Cadence of the transitional in-browser strategy stub (Phase 09). */
const SIGNAL_INTERVAL_MS = 30_000;
/** No ack within this window → the single idempotent retry, then failed. */
const ACK_TIMEOUT_MS = 5_000;

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

  // --- Phase 09: transitional in-browser decision loop (documented, ADR 0010) ---

  private lastContextState: MarketContextState | null = null;

  private lastRisk: { state: RiskState; policy: RiskPolicy } | null = null;

  private signalTimer: ReturnType<typeof setInterval> | null = null;

  private signalCounter = 100;

  /** Session-unique id prefix: prevents cross-session/tab commandId collisions
   *  against the agent's persistent dedup set (seen live on 2026-07-11). */
  private readonly runId = Date.now().toString(36).slice(-4);

  /** Commands awaiting an ack: single 5s timeout → one retry (same id) → failed. */
  private pendingAcks = new Map<
    string,
    { command: PlaceOrderCommand; timer: ReturnType<typeof setTimeout>; retried: boolean }
  >();

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
        this.startSignalLoop();
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
    if (this.signalTimer) {
      clearInterval(this.signalTimer);
      this.signalTimer = null;
    }
    for (const pending of this.pendingAcks.values()) {
      clearTimeout(pending.timer);
    }
    this.pendingAcks.clear();
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
      // Phase 09: agent/gateway receipt — settle the pending ack timer, then
      // let the store drive the command/signal lifecycle.
      case "execution.command.acknowledged":
      case "execution.command.rejected": {
        const { ack } = envelope.payload as CommandAckPayload;
        const pending = this.pendingAcks.get(ack.commandId);
        if (pending) {
          clearTimeout(pending.timer);
          this.pendingAcks.delete(ack.commandId);
        }
        this.store.apply(envelope);
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
    this.lastContextState = state;
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
    this.lastRisk = { state, policy };
    this.store.hydrate({ risk: toRiskStatusReadModel(state, policy) });
  }

  // --- Phase 09: Signal → RiskDecision → ExecutionCommand (observe loop) ---
  // Transitional: the strategy stub + risk review run in the browser on REAL
  // context/risk (engine port to the backend is a later phase, ADR 0010).
  // Business logic lives in lib/strategy-stub, lib/risk, lib/execution.

  private startSignalLoop(): void {
    if (this.signalTimer) {
      return;
    }
    this.signalTimer = setInterval(() => this.runDecisionLoop(), SIGNAL_INTERVAL_MS);
  }

  private runDecisionLoop(): void {
    const { connection, account } = this.store.getSnapshot();
    if (connection !== "connected" || !account || !this.lastContextState || !this.lastRisk) {
      return; // only decide on fresh, fully-hydrated real state
    }
    if (this.lastBid === null) {
      return;
    }

    this.signalCounter += 1;
    const signal = mockStrategySignal({
      context: this.lastContextState,
      account,
      price: this.lastBid,
      seq: this.signalCounter,
      runId: this.runId,
    });
    // Phase 10: signals/decisions are PUBLISHED through the hub, which
    // persists them and rebroadcasts to every dashboard (multi-tab
    // consistency + audit). The store applies them when they come back.
    this.publish(
      makeEnvelope<SignalCreatedPayload>("strategy.signal.created", "cockpit-strategy-stub", {
        signal: toStrategySignalReadModel(signal),
      }),
    );

    const decision = evaluateSignalRisk({
      signalId: signal.signalId,
      accountId: signal.accountId,
      entryPrice: signal.entryPrice,
      stopLoss: signal.stopLoss,
      balance: account.balance,
      state: this.lastRisk.state,
      policy: this.lastRisk.policy,
      now: new Date().toISOString(),
    });
    this.publish(
      makeEnvelope<RiskDecisionMadePayload>("risk.decision.made", "cockpit-risk-engine", {
        decision: toRiskDecisionView(decision),
      }, signal.signalId),
    );

    // Only an approved, sized decision can become a command (builder enforces it).
    const agentId = this.store.getSnapshot().agents[0]?.agentId ?? "mt5-observer-1";
    const command = buildPlaceOrderCommand({
      signal,
      decision,
      agentId,
      now: new Date().toISOString(),
    });
    if (command) {
      this.submitCommand(command, false);
    }
  }

  /** Publish a whitelisted envelope through the hub (persist + rebroadcast).
   *  Falls back to a local apply if the invoke fails, so the operator still
   *  sees the fact even when the hub write is lost. */
  private publish(envelope: Envelope<unknown>): void {
    if (!this.connection) {
      this.store.apply(envelope as Envelope);
      return;
    }
    void this.connection.invoke("PublishEvent", envelope).catch(() => {
      this.store.apply(envelope as Envelope);
    });
  }

  /** Submit to the hub and arm the ack timeout (one idempotent retry, then failed). */
  private submitCommand(command: PlaceOrderCommand, isRetry: boolean): void {
    if (!this.connection) {
      return;
    }
    void this.connection.invoke("SubmitCommand", command).catch(() => {
      // invoke failed outright (e.g. reconnecting) — the timeout path handles it.
    });
    const timer = setTimeout(() => this.onAckTimeout(command.commandId), ACK_TIMEOUT_MS);
    this.pendingAcks.set(command.commandId, { command, timer, retried: isRetry });
  }

  private onAckTimeout(commandId: string): void {
    const pending = this.pendingAcks.get(commandId);
    if (!pending) {
      return;
    }
    this.pendingAcks.delete(commandId);
    if (!pending.retried) {
      // Single retry with the SAME commandId — the agent dedupes (DUPLICATE
      // ack counts as confirmation), which exercises idempotency for real.
      this.store.markCommandRetried(commandId);
      this.submitCommand(pending.command, true);
      return;
    }
    this.store.markCommandFailed(commandId, "no ack within timeout (after retry)");
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
