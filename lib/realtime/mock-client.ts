/**
 * Mock implementation of the realtime gateway connection.
 *
 * It reproduces the exact behavior the future SignalR client must have
 * (context/realtime/dashboard_realtime_model.md):
 *   1. connect, 2. initial snapshot, 3. event stream + heartbeats,
 *   4. stale on missed heartbeats, 5. snapshot resync after reconnect.
 *
 * A scripted outage runs periodically so every connection state is
 * observable in the UI without touching the code.
 */

import { makeEnvelope } from "@/lib/mock/envelope";
import {
  mockAccount,
  mockAgents,
  mockAlerts,
  mockExecutionReports,
  mockMarketContext,
  mockPnlCalendar,
  mockPositions,
  mockRisk,
  mockUpcomingReleases,
} from "@/lib/mock/initial-snapshot";
import { mockCandles, nextCandles } from "@/lib/mock/candles";
import { analyzeMarketContext } from "@/lib/analysis";
import { toMarketContextReadModel } from "@/lib/contracts/projections";
import type { Candle } from "@/lib/domain/market";
import type {
  AgentHeartbeatPayload,
  MarketContextUpdatedPayload,
  MarketTickPayload,
  RiskLockoutAcknowledgedPayload,
  RiskLockoutClearedPayload,
  RiskLockoutEnabledPayload,
} from "@/lib/contracts/events";
import { clearedByForAck, KILL_SWITCH_REASON } from "@/lib/risk";
import { fetchAccountSettings } from "@/lib/accounts/settings-api";
import type { RealtimeClient } from "./client";
import type { CockpitStore } from "./store";

function makeId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** A plausible trading-day anchor for the scripted account: today, 00:00
 *  UTC. Real anchors are server midnight, Gateway-resolved (T02a). */
function mockDayAnchor(): string {
  const now = new Date();
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())).toISOString();
}

const TICK_INTERVAL_MS = 1_500;
const HEARTBEAT_INTERVAL_MS = 3_000;
const WATCHDOG_INTERVAL_MS = 2_000;
const HEARTBEAT_STALE_AFTER_MS = 7_000;
const CONTEXT_UPDATE_INTERVAL_MS = 12_000;
const CONNECTED_PERIOD_MS = 40_000;
const STALE_PERIOD_MS = 10_000;
const RECONNECT_PERIOD_MS = 4_000;

export class MockRealtimeClient implements RealtimeClient {
  private timers: ReturnType<typeof setTimeout>[] = [];

  private stopped = false;

  private heartbeatsSuspended = false;

  private price = 3312.1;

  /** Evolving candle window the ICT/SMC engine recomputes context from. */
  private candles: Candle[] = mockCandles();

  constructor(private readonly store: CockpitStore) {}

  start(): void {
    this.stopped = false;
    this.store.setConnectionState("connecting");
    this.after(600, () => this.goOnline(true));
  }

  stop(): void {
    this.stopped = true;
    for (const timer of this.timers) {
      clearTimeout(timer);
    }
    this.timers = [];
  }

  /** T02a demo: mock risk data is static (mockRisk()), so the kill switch is
   *  the only lockout path exercised in mock mode — no-ops if already locked,
   *  same edge-trigger as the real client. */
  triggerKillSwitch(): void {
    const { account, activeLockout } = this.store.getSnapshot();
    if (!account || activeLockout !== null) {
      return;
    }
    this.store.apply(
      makeEnvelope<RiskLockoutEnabledPayload>("risk.lockout.enabled", "mock-risk-engine", {
        lockoutId: makeId("lockout"),
        accountId: account.accountId,
        reason: KILL_SWITCH_REASON,
        since: new Date().toISOString(),
        until: null,
      }),
    );
  }

  /** T02c: the ack IS the manual-clear action for any untimed lockout — none
   *  of them auto-clear via a timer or the next day any more. */
  acknowledgeLockout(lockoutId: string): void {
    const { account, activeLockout } = this.store.getSnapshot();
    if (!account) {
      return;
    }
    this.store.apply(
      makeEnvelope<RiskLockoutAcknowledgedPayload>("risk.lockout.acknowledged", "mock-cockpit", {
        accountId: account.accountId,
        lockoutId,
        acknowledgedAt: new Date().toISOString(),
      }),
    );
    this.store.apply(
      makeEnvelope<RiskLockoutClearedPayload>("risk.lockout.cleared", "mock-risk-engine", {
        accountId: account.accountId,
        clearedBy: clearedByForAck(activeLockout?.reason ?? ""),
      }),
    );
  }

  refreshAccountSettings(): void {
    fetchAccountSettings()
      .then((ledger) => {
        if (!this.stopped) {
          this.store.hydrate({ accountSettings: ledger, accountSettingsError: null });
        }
      })
      .catch((error: unknown) => {
        if (!this.stopped) {
          this.store.hydrate({
            accountSettingsError: error instanceof Error ? error.message : "Lecture impossible.",
          });
        }
      });
  }

  private goOnline(initial: boolean): void {
    this.store.setConnectionState("connected");
    this.heartbeatsSuspended = false;
    // Resync the candle window so snapshot and stream start from one series.
    this.candles = mockCandles();
    // Snapshot on connect, resync on every reconnect: same rule as SignalR later.
    this.store.hydrate({
      account: mockAccount(),
      positions: mockPositions(),
      risk: mockRisk(),
      marketContext: mockMarketContext(),
      agents: mockAgents(),
      executionReports: initial
        ? mockExecutionReports()
        : this.store.getSnapshot().executionReports,
      pnlCalendar: mockPnlCalendar(),
      alerts: mockAlerts(),
      lastHeartbeatAt: new Date().toISOString(),
      // T03: demo fixture only, static — not wired to a scenario.
      upcomingReleases: mockUpcomingReleases(),
      // Demo fixture: mock mode shows the execution agent as reachable so the
      // preflight verdict is demonstrable. Real mode reads this from
      // Mt5AgentServer.IsConnected, never from mockAgents().
      executionAgentConnected: true,
      dayAnchorStartsAtUtc: mockDayAnchor(),
    });
    // T12 incrément 2: the settings ledger is real even here — like the
    // journal screens, Account and Settings read the backend over HTTP, and
    // say so when it is not running.
    this.refreshAccountSettings();

    if (initial) {
      this.every(TICK_INTERVAL_MS, () => this.emitTick());
      this.every(HEARTBEAT_INTERVAL_MS, () => this.emitHeartbeat());
      this.every(WATCHDOG_INTERVAL_MS, () => this.checkHeartbeat());
      this.every(CONTEXT_UPDATE_INTERVAL_MS, () => this.emitContextUpdate());
    }
    this.after(CONNECTED_PERIOD_MS, () => this.beginOutage());
  }

  /** Scripted degradation: heartbeats stop, watchdog marks stale, then reconnect. */
  private beginOutage(): void {
    this.heartbeatsSuspended = true;
    this.after(STALE_PERIOD_MS, () => {
      this.store.setConnectionState("reconnecting");
      this.store.apply(makeEnvelope("agent.disconnected", "mock-gateway", {}));
      this.after(RECONNECT_PERIOD_MS, () => this.goOnline(false));
    });
  }

  private checkHeartbeat(): void {
    const { connection, lastHeartbeatAt } = this.store.getSnapshot();
    if (connection !== "connected" || !lastHeartbeatAt) {
      return;
    }
    const age = Date.now() - new Date(lastHeartbeatAt).getTime();
    if (age > HEARTBEAT_STALE_AFTER_MS) {
      this.store.setConnectionState("stale");
    }
  }

  private emitTick(): void {
    if (this.heartbeatsSuspended) {
      return;
    }
    this.price = Math.round((this.price + (Math.random() - 0.5) * 0.9) * 100) / 100;
    this.store.apply(
      makeEnvelope<MarketTickPayload>("market.tick", "mock-market-data", {
        symbol: "XAUUSD",
        bid: this.price,
        ask: Math.round((this.price + 0.25) * 100) / 100,
      }),
    );
  }

  private emitHeartbeat(): void {
    if (this.heartbeatsSuspended) {
      return;
    }
    this.store.apply(
      makeEnvelope<AgentHeartbeatPayload>("agent.heartbeat", "mt5-agent-001", {
        agentId: "mt5-agent-001",
        latencyMs: 30 + Math.round(Math.random() * 25),
      }),
    );
  }

  /** Advance the candle window and re-run the ICT/SMC engine on it. */
  private emitContextUpdate(): void {
    if (this.heartbeatsSuspended) {
      return;
    }
    this.candles = nextCandles(this.candles);
    const context = toMarketContextReadModel(
      analyzeMarketContext({ symbol: "XAUUSD", timeframe: "M15", candles: this.candles }),
    );
    this.store.apply(
      makeEnvelope<MarketContextUpdatedPayload>(
        "analysis.market_context.updated",
        "mock-analysis-engine",
        { context },
      ),
    );
  }

  private after(ms: number, fn: () => void): void {
    if (this.stopped) {
      return;
    }
    this.timers.push(
      setTimeout(() => {
        if (!this.stopped) {
          fn();
        }
      }, ms),
    );
  }

  private every(ms: number, fn: () => void): void {
    const loop = () => {
      fn();
      this.after(ms, loop);
    };
    this.after(ms, loop);
  }
}
