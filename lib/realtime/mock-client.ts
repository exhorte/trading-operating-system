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

import { makeEnvelope, uuid } from "@/lib/mock/envelope";
import {
  mockAccount,
  mockAgents,
  mockAlerts,
  mockExecutionReports,
  mockMarketContext,
  mockPnlCalendar,
  mockPositions,
  mockRisk,
  mockRiskContext,
  mockSignals,
  mockUpcomingReleases,
} from "@/lib/mock/initial-snapshot";
import { mockStrategySignal } from "@/lib/mock/signals";
import type { MockRiskScenario } from "@/lib/mock/initial-snapshot";
import { mockCandles, nextCandles } from "@/lib/mock/candles";
import { analyzeMarketContext } from "@/lib/analysis";
import { evaluateSignalRisk } from "@/lib/risk";
import {
  toMarketContextReadModel,
  toRiskDecisionView,
  toRiskStatusReadModel,
  toStrategySignalReadModel,
} from "@/lib/contracts/projections";
import type { Candle } from "@/lib/domain/market";
import type { StrategySignal as DomainStrategySignal } from "@/lib/domain/strategy";
import type {
  AgentHeartbeatPayload,
  ExecutionReportPayload,
  MarketContextUpdatedPayload,
  MarketTickPayload,
  RiskDecisionMadePayload,
  RiskLockoutAcknowledgedPayload,
  RiskLockoutClearedPayload,
  RiskLockoutEnabledPayload,
  RiskStateUpdatedPayload,
  SignalCreatedPayload,
  TicketCreatedPayload,
} from "@/lib/contracts/events";
import { KILL_SWITCH_REASON } from "@/lib/risk";
import type { PreTradeTicket } from "@/lib/domain/ticket";
import type { RealtimeClient } from "./client";
import type { CockpitStore } from "./store";

function makeId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

const TICK_INTERVAL_MS = 1_500;
const HEARTBEAT_INTERVAL_MS = 3_000;
const WATCHDOG_INTERVAL_MS = 2_000;
const HEARTBEAT_STALE_AFTER_MS = 7_000;
const CONTEXT_UPDATE_INTERVAL_MS = 12_000;
const SIGNAL_INTERVAL_MS = 15_000;
const CONNECTED_PERIOD_MS = 40_000;
const STALE_PERIOD_MS = 10_000;
const RECONNECT_PERIOD_MS = 4_000;

export class MockRealtimeClient implements RealtimeClient {
  private timers: ReturnType<typeof setTimeout>[] = [];

  private stopped = false;

  private heartbeatsSuspended = false;

  private price = 3312.1;

  private signalCounter = 15;

  /** Domain signal awaiting risk review on the next tick (Signal → Risk Review). */
  private pendingReview: DomainStrategySignal | null = null;

  /** Rotating market/risk conditions so reviews also produce rejections. */
  private reviewCounter = 0;

  private static readonly SCENARIOS: MockRiskScenario[] = [
    "normal",
    "normal",
    "wide_spread",
    "normal",
    "closed_session",
    "normal",
    "news_blackout",
  ];

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

  /** No real hub in mock mode: echo immediately, same as a successful publish. */
  publishTicket(ticket: PreTradeTicket): void {
    this.store.apply(
      makeEnvelope<TicketCreatedPayload>("journal.ticket.created", "mock-cockpit", { ticket }, ticket.ticketId),
    );
  }

  /** T02a demo: the mock's own scenarios never breach a real threshold (see
   *  mockRiskContext), so the kill switch is the only lockout path exercised
   *  in mock mode — no-ops if already locked, same edge-trigger as the real
   *  client. */
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

  /** The ack IS the manual-clear action for the kill switch — it never
   *  auto-clears via a timer or the next day (see shouldAutoClearForNewDay). */
  acknowledgeLockout(lockoutId: string): void {
    const account = this.store.getSnapshot().account;
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
        clearedBy: "kill-switch-ack",
      }),
    );
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
      signals: initial ? mockSignals() : this.store.getSnapshot().signals,
      agents: mockAgents(),
      executionReports: initial
        ? mockExecutionReports()
        : this.store.getSnapshot().executionReports,
      pnlCalendar: mockPnlCalendar(),
      alerts: mockAlerts(),
      lastHeartbeatAt: new Date().toISOString(),
      // T03: demo fixture only — not synced with the rotating risk scenario
      // below, same documented limitation as mockRiskContext (T02a journal).
      upcomingReleases: mockUpcomingReleases(),
    });

    if (initial) {
      this.every(TICK_INTERVAL_MS, () => this.emitTick());
      this.every(HEARTBEAT_INTERVAL_MS, () => this.emitHeartbeat());
      this.every(WATCHDOG_INTERVAL_MS, () => this.checkHeartbeat());
      this.every(CONTEXT_UPDATE_INTERVAL_MS, () => this.emitContextUpdate());
      this.every(SIGNAL_INTERVAL_MS, () => this.advanceSignals());
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

  /**
   * Signal → Risk Review. One tick reviews the pending signal with the REAL
   * risk engine (evaluateSignalRisk against the current risk state), the next
   * creates a fresh signal from the computed market context. No more faked
   * score-threshold approvals.
   */
  private advanceSignals(): void {
    if (this.heartbeatsSuspended) {
      return;
    }

    if (this.pendingReview) {
      const signal = this.pendingReview;
      this.pendingReview = null;
      // Rotate market/risk conditions and publish the SAME state to the Risk
      // panel that the review uses, so an approval/rejection always matches
      // what the cockpit shows (wide spread and closed session cause real
      // gate rejections).
      const scenario =
        MockRealtimeClient.SCENARIOS[this.reviewCounter % MockRealtimeClient.SCENARIOS.length];
      this.reviewCounter += 1;
      const { state, policy, balance } = mockRiskContext(scenario);
      this.store.apply(
        makeEnvelope<RiskStateUpdatedPayload>("risk.state.updated", "mock-risk-engine", {
          risk: toRiskStatusReadModel(state, policy),
        }),
      );
      const decision = evaluateSignalRisk({
        signalId: signal.signalId,
        accountId: signal.accountId,
        entryPrice: signal.entryPrice,
        stopLoss: signal.stopLoss,
        balance,
        state,
        policy,
        now: new Date().toISOString(),
      });
      this.store.apply(
        makeEnvelope<RiskDecisionMadePayload>(
          "risk.decision.made",
          "mock-risk-engine",
          { decision: toRiskDecisionView(decision) },
          signal.signalId,
        ),
      );
      if (decision.approved) {
        this.after(2_500, () => this.emitFillReport(signal, decision.approvedVolume));
      }
      return;
    }

    this.signalCounter += 1;
    const context = analyzeMarketContext({
      symbol: "XAUUSD",
      timeframe: "M15",
      candles: this.candles,
    });
    const signal = mockStrategySignal({
      context,
      account: mockAccount(),
      price: this.price,
      seq: this.signalCounter,
    });
    this.pendingReview = signal;
    this.store.apply(
      makeEnvelope<SignalCreatedPayload>("strategy.signal.created", "mock-strategy-engine", {
        signal: toStrategySignalReadModel(signal),
      }),
    );
  }

  private emitFillReport(signal: DomainStrategySignal, volume: number | null): void {
    if (this.heartbeatsSuspended) {
      return;
    }
    this.store.apply(
      makeEnvelope<ExecutionReportPayload>("execution.order.filled", "mt5-agent-001", {
        report: {
          reportId: uuid(),
          commandId: `cmd-${signal.signalId}`,
          correlationId: `corr-${signal.signalId}`,
          accountId: signal.accountId,
          agentId: "mt5-agent-001",
          symbol: signal.symbol,
          side: signal.side,
          status: "filled",
          detail: `Mock fill ${volume ?? "?"} lot for ${signal.signalId}, TRADE_RETCODE_DONE`,
          reportedAt: new Date().toISOString(),
        },
      }),
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
