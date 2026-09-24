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
 * Not purely read-only: also publishes whitelisted dashboard facts through
 * PublishEvent (see CockpitHub.PublishableTypes).
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
  clearedByForAck,
  CONSECUTIVE_LOSS_PAUSE_MINUTES,
  defaultRiskPolicy,
  detectConsecutiveLossPause,
  detectNewLockout,
  evaluateRiskState,
  isLockoutExpired,
  KILL_SWITCH_REASON,
} from "@/lib/risk";
import { resolveActiveProfile } from "@/lib/accounts/active-profile";
import {
  DEFAULT_ACCOUNT_SETTINGS,
  nextDayAnchor,
  resolveAccountSettings,
  type DayAnchorState,
} from "@/lib/accounts/settings";
import { fetchAccountSettings } from "@/lib/accounts/settings-api";
import { makeEnvelope } from "@/lib/mock/envelope";
import { toMarketContextReadModel, toRiskStatusReadModel } from "@/lib/contracts/projections";
import type { Envelope } from "@/lib/contracts/envelope";
import type {
  AgentHeartbeatPayload,
  DayAnchorResolvedPayload,
  MarketCandlePayload,
  MarketTickPayload,
  PositionOpenedPayload,
  RiskLockoutAcknowledgedPayload,
  RiskLockoutClearedPayload,
  RiskLockoutEnabledPayload,
  TradeClosedPayload,
} from "@/lib/contracts/events";
import type {
  AccountSummary,
  AgentStatus,
  Position,
} from "@/lib/contracts/snapshots";
import type { Candle } from "@/lib/domain/market";
import type { UpcomingRelease } from "@/lib/domain/risk";
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

/** Shape returned by CockpitHub.GetSnapshot (C# CockpitSnapshotDto, camelCase). */
interface HubSnapshot {
  account: AccountSummary | null;
  positions: Position[];
  agents: AgentStatus[];
  candles: Candle[];
  /** Mt5AgentServer.IsConnected. `agents` above is the observer's hello and
   *  never answers for the execution agent — see CockpitSnapshotDto. */
  executionAgentConnected: boolean;
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

  /** T12 incrément 2: the anchor published to the store for settings
   *  resolution, and whose it is — see nextDayAnchor. */
  private publishedAnchor: DayAnchorState | null = null;

  /** T02a: real open-count since the day anchor, hydrated from /api/risk/today
   *  and kept current by re-hydrating on every journal.position.opened (T05:
   *  Gateway-detected, no longer a client-side counter). Null (not 0) until
   *  hydration succeeds — never a guessed zero. */
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

  /** True between publishing risk.lockout.enabled and the hub echoing it back
   *  into the store — see the comment at its only write site. */
  private lockoutPublishPending = false;

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
      executionAgentConnected: snapshot.executionAgentConnected,
    });
    this.scheduleContextRecompute();
    if (snapshot.account) {
      await this.hydrateRiskToday(snapshot.account.accountId);
    }
    // T03: not account-scoped (the FRED calendar is global) — always attempted.
    await this.hydrateCalendar();
    // T12 incrément 2: before the first risk computation, so the configured
    // challenge/reference apply from the first tick rather than the defaults.
    await this.hydrateAccountSettings();
    this.recomputeRisk();
  }

  /**
   * T12 incrément 2: the account settings ledger (GET /api/account-settings),
   * on every connect/reconnect and every accounts.settings.changed. A failed
   * read keeps the last ledger read successfully — silently falling back to
   * the code's defaults would swap the trader's configured reference for
   * another one mid-session.
   */
  private async hydrateAccountSettings(): Promise<void> {
    try {
      const ledger = await fetchAccountSettings();
      this.store.hydrate({ accountSettings: ledger, accountSettingsError: null });
    } catch (error) {
      this.store.hydrate({
        accountSettingsError: error instanceof Error ? error.message : "Lecture impossible.",
      });
    }
  }

  refreshAccountSettings(): void {
    void this.hydrateAccountSettings().then(() => this.recomputeRisk());
  }

  /**
   * T12 incrément 2: the anchor settings deferred to "the next trading day"
   * resolve against — the same one the daily loss uses. Fed by the anchor
   * event itself and by /api/risk/today, never stepping back within one
   * account (nextDayAnchor: the database row can lag the event).
   */
  private publishDayAnchor(accountId: string, startsAtUtc: string | null): void {
    const next = nextDayAnchor(this.publishedAnchor, { accountId, startsAtUtc });
    this.publishedAnchor = next;
    if (this.store.getSnapshot().dayAnchorStartsAtUtc !== next.startsAtUtc) {
      this.store.hydrate({ dayAnchorStartsAtUtc: next.startsAtUtc });
    }
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
      this.publishDayAnchor(accountId, data.dayAnchorStartsAtUtc);
    } catch {
      // Best-effort: live events and the per-tab baseline fallback still work.
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
        this.recomputeRisk();
        break;
      }
      // T05: Gateway-detected (server-side positions.snapshot diff) — like
      // journal.trade_closed, re-hydrate the persisted truth rather than
      // trying to patch a local counter (that counter was the T02a bug this
      // migration fixes: silently missed opens with no cockpit tab open).
      case "journal.position.opened": {
        const { accountId } = envelope.payload as PositionOpenedPayload;
        void this.hydrateRiskToday(accountId);
        break;
      }
      // T02a: Gateway-resolved — a genuinely new anchor means a new trading
      // day (or the very first resolution): re-hydrate the persisted truth
      // rather than trying to patch scattered local counters.
      case "risk.day_anchor.resolved": {
        const { accountId, startsAtUtc } = envelope.payload as DayAnchorResolvedPayload;
        if (startsAtUtc !== this.dayAnchorStartsAtUtc) {
          // T12 incrément 2: the event carries the anchor — publish it now,
          // so settings deferred to this new day take effect without waiting
          // for the database row hydrateRiskToday reads back (written
          // asynchronously), then recompute once hydrated.
          this.publishDayAnchor(accountId, startsAtUtc);
          void this.hydrateRiskToday(accountId).then(() => this.recomputeRisk());
        }
        break;
      }
      // T12 incrément 2: backend-originated, after every write to the
      // settings ledger — re-read it rather than patch it, same pattern as
      // journal.trade_closed.
      case "accounts.settings.changed": {
        this.refreshAccountSettings();
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

  /** Real spread, real trade count since the day anchor (T02a), real
   *  consecutive-loss streak (T02b). The lockout ledger — not this
   *  computation — decides "locked right now" (see applyActiveLockout). */
  private recomputeRisk(): void {
    const {
      account,
      positions,
      activeLockout,
      upcomingReleases,
      executionAgentConnected,
      accountSettings,
      dayAnchorStartsAtUtc,
    } = this.store.getSnapshot();
    if (!account || this.baselineBalance === null || this.baselineEquity === null) {
      return;
    }
    // T12: the terminal's firm decides which rules and which reference
    // balance apply. Unrecognised broker -> the pre-T12 behaviour, unchanged.
    // T12 incrément 2: with the settings in effect today — a change deferred
    // to the next trading day stays out until its anchor has started.
    const settings = accountSettings
      ? resolveAccountSettings(accountSettings.versions, dayAnchorStartsAtUtc).settings
      : DEFAULT_ACCOUNT_SETTINGS;
    const active = resolveActiveProfile(account, settings);
    const policy = active?.riskPolicy ?? defaultRiskPolicy(account.accountId);
    const spreadPoints =
      this.lastAsk !== null && this.lastBid !== null
        ? Math.round((this.lastAsk - this.lastBid) / 0.01)
        : null;
    const nowIso = new Date().toISOString();
    const session = sessionForTimestamp(nowIso, DEFAULT_SESSION_WINDOWS);
    // T09: still never "unknown" — the hub states the execution agent's
    // connection explicitly, at hydration and on every change.
    // Fixed 2026-09-18: this used to be `agents.some(a => a.state ===
    // "connected")`, but `agents` only ever holds the READ-ONLY observer's
    // hello (GatewayState.SetHello is called from Mt5ObserverClient, never
    // from Mt5AgentServer). So the gate reported "execution agent reachable"
    // whenever the market feed was up, with no EA-05 agent connected at all —
    // exactly the false confidence T09 was built to remove.
    const agentConnected = executionAgentConnected;
    const computed = evaluateRiskState({
      policy,
      // T12 fix. Overall loss was measured from `baselineBalance` — the
      // balance when this tab last (re)connected, reset on every resync. A
      // prop firm measures it from the account's initial size, fixed for the
      // whole challenge: on a 10 000 $ FTMO account reopened at 9 400 $, the
      // gate allowed a floor of 8 460 $ while FTMO had already closed the
      // account at 9 000 $. The profile's reference wins whenever it exists.
      // Daily loss never had this flaw: `baselineEquity` below is the
      // persisted start-of-day equity (T02a, hydrateRiskToday).
      initialBalance: active?.referenceBalance ?? this.baselineBalance,
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
      agentConnected,
      session,
      sessionTradingEnabled: sessionEnabled(session, DEFAULT_SESSION_WINDOWS),
      upcomingReleases,
      now: nowIso,
    });

    // The store only learns about a lockout once the hub echoes the published
    // event back; until then `activeLockout` is still null and every risk
    // recomputation in that window (ticks arrive continuously) re-fires the
    // edge-trigger and writes another ledger row — four rows 73 ms apart,
    // observed for real on 2026-09-14. detectNewLockout is correctly
    // edge-triggered on its own input; it's this caller that was feeding it a
    // stale "not locked yet". The flag clears the moment the echo lands, so it
    // can never mask a genuinely new lock.
    if (activeLockout !== null) {
      this.lockoutPublishPending = false;
    }
    const newLockout = detectNewLockout(computed, activeLockout);
    if (newLockout && !this.lockoutPublishPending) {
      this.lockoutPublishPending = true;
      this.publishLockoutEnabled(makeId("lockout"), account.accountId, newLockout.reason);
    }
    const newPause = detectConsecutiveLossPause(
      computed,
      activeLockout,
      this.lastConsecutiveLossAt,
      CONSECUTIVE_LOSS_PAUSE_MINUTES,
    );
    if (newPause && !this.lockoutPublishPending) {
      this.lockoutPublishPending = true;
      this.publishLockoutEnabled(makeId("lockout"), account.accountId, newPause.reason, newPause.until);
    }
    // T02c: no untimed lockout auto-clears at the day anchor any more —
    // daily loss and max trades now require the same explicit ack as the
    // kill switch (see acknowledgeLockout, clearedByForAck). Two real
    // incidents (state.md) went unacknowledged overnight under the old
    // shouldAutoClearForNewDay behavior, since removed.
    // T02b: a timed pause whose clock ran out must not keep locking the
    // account, and the ledger shouldn't keep a stale "active" row either —
    // the backend's own /api/risk/today filter is only the backup for this.
    if (activeLockout && isLockoutExpired(activeLockout, nowIso)) {
      this.publishLockoutCleared(account.accountId, "pause-expired");
    }
    const state = applyActiveLockout(computed, activeLockout, nowIso);

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
   * T02a/T02c: the trader's own record of having taken note of an untimed
   * lockout — since none of them auto-clear any more (no timer, no next-day
   * reset), this ack is the only way any of them is ever released.
   * clearedByForAck keeps the kill switch's own long-standing audit value
   * ("kill-switch-ack") distinct from every other reason ("manual").
   */
  acknowledgeLockout(lockoutId: string): void {
    const { account, activeLockout } = this.store.getSnapshot();
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
    this.publishLockoutCleared(account.accountId, clearedByForAck(activeLockout?.reason ?? ""));
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
