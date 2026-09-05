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
 * Not purely read-only: also submits observe-mode commands (never a real
 * trade call — see command-builder.ts) and publishes whitelisted dashboard
 * facts (signal/decision reviews, T04 tickets) through PublishEvent.
 */

import {
  HubConnection,
  HubConnectionBuilder,
  HubConnectionState,
} from "@microsoft/signalr";
import { analyzeMarketContext, DEFAULT_SESSION_WINDOWS } from "@/lib/analysis";
import { sessionEnabled, sessionForTimestamp } from "@/lib/analysis/sessions";
import {
  applyActiveLockout,
  CONSECUTIVE_LOSS_PAUSE_MINUTES,
  defaultRiskPolicy,
  detectConsecutiveLossPause,
  detectNewLockout,
  evaluateRiskState,
  evaluateSignalRisk,
  isLockoutExpired,
  KILL_SWITCH_REASON,
  shouldAutoClearForNewDay,
} from "@/lib/risk";
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
  DayAnchorResolvedPayload,
  MarketCandlePayload,
  MarketTickPayload,
  PositionOpenedPayload,
  RiskDecisionMadePayload,
  RiskLockoutAcknowledgedPayload,
  RiskLockoutClearedPayload,
  RiskLockoutEnabledPayload,
  SignalCreatedPayload,
  TicketCreatedPayload,
  TradeClosedPayload,
} from "@/lib/contracts/events";
import type { PreTradeTicket } from "@/lib/domain/ticket";
import type { CommandAckPayload } from "@/lib/contracts/commands";
import type {
  AccountSummary,
  AgentStatus,
  Position,
} from "@/lib/contracts/snapshots";
import type { Candle } from "@/lib/domain/market";
import type { MarketContextState } from "@/lib/domain/analysis";
import type { PlaceOrderCommand } from "@/lib/domain/execution";
import type { RiskPolicy, RiskState, UpcomingRelease } from "@/lib/domain/risk";
import type { ActiveLockout } from "@/lib/risk/lockout";
import type { RealtimeClient } from "./client";
import type { CockpitStore } from "./store";

/** T02a/T02b: shape of GET /api/risk/today (RiskTodayRepository.RiskTodaySummary). */
interface RiskTodaySummary {
  dayAnchorStartsAtUtc: string | null;
  dayStartEquity: number | null;
  tradesToday: number;
  consecutiveLosses: number;
  lastConsecutiveLossAt: string | null;
  activeLockout: ActiveLockout | null;
}

function makeId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

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

  /** T02a: the current trading day's anchor (server midnight, resolved by the
   *  Gateway) — null until the first risk.day_anchor.resolved arrives. */
  private dayAnchorStartsAtUtc: string | null = null;

  /** T02a: brokerPositionIds already published this session — a reload
   *  re-detects and re-publishes them too, which the server dedupes
   *  (ON CONFLICT DO NOTHING), so this only needs to avoid same-session spam. */
  private knownPositionIds = new Set<string>();

  /** T02a: real open-count since the day anchor, hydrated from /api/risk/today
   *  and kept current as this.publishNewPositions detects more. Null (not 0)
   *  until hydration succeeds — never a guessed zero. */
  private tradesToday: number | null = null;

  /** T02b: real trailing loss streak, hydrated from /api/risk/today and kept
   *  current by the journal.trade_closed re-hydration below. Null only until
   *  the first hydration succeeds — never a guessed 0. */
  private consecutiveLosses: number | null = null;

  /** T02b: when the most recent loss in that streak closed — the anchor the
   *  30-minute pause counts from (detectConsecutiveLossPause). */
  private lastConsecutiveLossAt: string | null = null;

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
    if (snapshot.account) {
      await this.hydrateRiskToday(snapshot.account.accountId);
      this.publishNewPositions(snapshot.account.accountId);
    }
    // T03: not account-scoped (the FRED calendar is global) — always attempted.
    await this.hydrateCalendar();
    this.recomputeRisk();
  }

  /**
   * T03: the backend's FRED cache (GET /api/calendar/upcoming), hydrated on
   * every connect/reconnect. A failed/unreachable fetch leaves
   * store.upcomingReleases as it was (null on first connect) — newsGate
   * fails CLOSED on null, so this never silently opens the blackout gate.
   */
  private async hydrateCalendar(): Promise<void> {
    const base = this.hubUrl.replace(/\/hub\/cockpit\/?$/, "");
    try {
      const res = await fetch(`${base}/api/calendar/upcoming`);
      if (!res.ok) {
        return;
      }
      const data = (await res.json()) as { releases: UpcomingRelease[] | null };
      this.store.hydrate({ upcomingReleases: data.releases });
    } catch {
      // Best-effort: the news gate stays fail-closed until this succeeds.
    }
  }

  /**
   * T02a: read the persisted truth for this account — the day anchor, the
   * real trade count since it, and any active lockout — so a fresh
   * connection shows the right numbers immediately instead of a guessed
   * baseline (see the state-persistence gap this replaces).
   */
  private async hydrateRiskToday(accountId: string): Promise<void> {
    const base = this.hubUrl.replace(/\/hub\/cockpit\/?$/, "");
    try {
      const res = await fetch(`${base}/api/risk/today?accountId=${encodeURIComponent(accountId)}`);
      if (!res.ok) {
        return;
      }
      const data = (await res.json()) as RiskTodaySummary;
      this.dayAnchorStartsAtUtc = data.dayAnchorStartsAtUtc;
      this.tradesToday = data.tradesToday;
      this.consecutiveLosses = data.consecutiveLosses;
      this.lastConsecutiveLossAt = data.lastConsecutiveLossAt;
      if (data.dayStartEquity !== null) {
        this.baselineEquity = data.dayStartEquity;
      }
      this.store.hydrate({ activeLockout: data.activeLockout });
    } catch {
      // Best-effort: live events and the per-tab baseline fallback still work.
    }
  }

  /**
   * T02a: a brokerPositionId seen for the first time this session is
   * published as an open — no P&L needed, just a count for the max-trades
   * gate. Runs on every snapshot, not only the first, so a trade opened
   * after connect is caught too.
   */
  private publishNewPositions(accountId: string): void {
    for (const position of this.store.getSnapshot().positions) {
      if (this.knownPositionIds.has(position.positionId)) {
        continue;
      }
      this.knownPositionIds.add(position.positionId);
      this.tradesToday = (this.tradesToday ?? 0) + 1;
      this.publish(
        makeEnvelope<PositionOpenedPayload>("journal.position.opened", "cockpit-risk-engine", {
          accountId,
          brokerPositionId: position.positionId,
          openedAt: position.openedAt,
        }),
      );
    }
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
        const account = this.store.getSnapshot().account;
        if (account) {
          this.publishNewPositions(account.accountId);
        }
        this.recomputeRisk();
        break;
      }
      // T02a: Gateway-resolved — a genuinely new anchor means a new trading
      // day (or the very first resolution): re-hydrate the persisted truth
      // rather than trying to patch scattered local counters.
      case "risk.day_anchor.resolved": {
        const { accountId, startsAtUtc } = envelope.payload as DayAnchorResolvedPayload;
        if (startsAtUtc !== this.dayAnchorStartsAtUtc) {
          void this.hydrateRiskToday(accountId);
        }
        break;
      }
      // T02b: Gateway-resolved fact (only the observer's deal history knows
      // a real close) — re-hydrate rather than recompute the streak
      // client-side, same pattern as risk.day_anchor.resolved.
      case "journal.trade_closed": {
        const { accountId } = envelope.payload as TradeClosedPayload;
        void this.hydrateRiskToday(accountId);
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

  /** Real spread, real trade count since the day anchor (T02a), real
   *  consecutive-loss streak (T02b). The lockout ledger — not this
   *  computation — decides "locked right now" (see applyActiveLockout). */
  private recomputeRisk(): void {
    const { account, positions, activeLockout, upcomingReleases } = this.store.getSnapshot();
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
    const computed = evaluateRiskState({
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
      tradesToday: this.tradesToday,
      consecutiveLosses: this.consecutiveLosses,
      spreadPoints,
      session,
      sessionTradingEnabled: sessionEnabled(session, DEFAULT_SESSION_WINDOWS),
      upcomingReleases,
      now: nowIso,
    });

    const newLockout = detectNewLockout(computed, activeLockout);
    if (newLockout) {
      this.publishLockoutEnabled(makeId("lockout"), account.accountId, newLockout.reason);
    }
    const newPause = detectConsecutiveLossPause(
      computed,
      activeLockout,
      this.lastConsecutiveLossAt,
      CONSECUTIVE_LOSS_PAUSE_MINUTES,
    );
    if (newPause) {
      this.publishLockoutEnabled(makeId("lockout"), account.accountId, newPause.reason, newPause.until);
    }
    if (
      activeLockout &&
      this.dayAnchorStartsAtUtc &&
      shouldAutoClearForNewDay(activeLockout, this.dayAnchorStartsAtUtc)
    ) {
      this.publishLockoutCleared(account.accountId, "next-day-reset");
    }
    // T02b: a timed pause whose clock ran out must not keep locking the
    // account, and the ledger shouldn't keep a stale "active" row either —
    // the backend's own /api/risk/today filter is only the backup for this.
    if (activeLockout && isLockoutExpired(activeLockout, nowIso)) {
      this.publishLockoutCleared(account.accountId, "pause-expired");
    }
    const state = applyActiveLockout(computed, activeLockout, nowIso);

    this.lastRisk = { state, policy };
    this.store.hydrate({ risk: toRiskStatusReadModel(state, policy) });
  }

  private publishLockoutEnabled(
    lockoutId: string,
    accountId: string,
    reason: string,
    until: string | null = null,
  ): void {
    this.publish(
      makeEnvelope<RiskLockoutEnabledPayload>("risk.lockout.enabled", "cockpit-risk-engine", {
        lockoutId,
        accountId,
        reason,
        since: new Date().toISOString(),
        until,
      }),
    );
  }

  private publishLockoutCleared(accountId: string, clearedBy: string): void {
    this.publish(
      makeEnvelope<RiskLockoutClearedPayload>("risk.lockout.cleared", "cockpit-risk-engine", {
        accountId,
        clearedBy,
      }),
    );
  }

  /**
   * T02a: manual kill switch. Locks the account for real (persisted ledger);
   * never a close_all command — the observer/wire has no such command, and a
   * SIMULATED reply that closes nothing real would be actively misleading.
   * No-ops if already locked (edge-triggered, like the automatic path).
   */
  triggerKillSwitch(): void {
    const { account, activeLockout } = this.store.getSnapshot();
    if (!account || activeLockout !== null) {
      return;
    }
    this.publishLockoutEnabled(makeId("lockout"), account.accountId, KILL_SWITCH_REASON);
  }

  /**
   * T02a: the trader's own record of having closed positions manually — and,
   * since the kill switch never auto-clears (no timer, no next-day reset:
   * see shouldAutoClearForNewDay), the only way this specific lock is ever
   * released. The ack IS the manual-clear action for this lock type.
   */
  acknowledgeLockout(lockoutId: string): void {
    const account = this.store.getSnapshot().account;
    if (!account) {
      return;
    }
    this.publish(
      makeEnvelope<RiskLockoutAcknowledgedPayload>("risk.lockout.acknowledged", "cockpit-journal", {
        accountId: account.accountId,
        lockoutId,
        acknowledgedAt: new Date().toISOString(),
      }),
    );
    this.publishLockoutCleared(account.accountId, "kill-switch-ack");
  }

  // --- Phase 09: Signal → RiskDecision → ExecutionCommand (observe loop) ---
  // Transitional: the strategy stub + risk review run in the browser on REAL
  // context/risk (engine port to the backend is a later phase, ADR 0010).
  // Business logic lives in lib/risk and lib/execution.

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
    // Signals/decisions are PUBLISHED through the hub, which
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

  /**
   * T04: publish a pre-trade ticket. Deliberately does NOT apply locally on
   * failure (unlike the internal `publish` below) — a ticket the caller
   * believes is saved but that never reached the hub must stay visibly
   * unconfirmed, not silently appear to succeed. The caller (TicketPanel)
   * is the one watching for the echo.
   */
  publishTicket(ticket: PreTradeTicket): void {
    if (!this.connection) {
      return;
    }
    void this.connection
      .invoke(
        "PublishEvent",
        makeEnvelope<TicketCreatedPayload>("journal.ticket.created", "cockpit-journal", { ticket }, ticket.ticketId),
      )
      .catch(() => {
        // Invoke itself failed (e.g. reconnecting) — no local fallback apply:
        // the caller's confirm-by-echo timeout is what surfaces this.
      });
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
