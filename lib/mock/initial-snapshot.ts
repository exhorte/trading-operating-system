/**
 * Deterministic-enough mock data used as the initial snapshot of every
 * subscription group. Values are plausible for an FTMO-style XAUUSD account
 * but carry no market meaning — the MOCK badge stays visible at all times.
 */

import type {
  AccountSummary,
  AgentStatus,
  CockpitAlert,
  ExecutionReport,
  MarketContext,
  PnlCalendarDay,
  Position,
  RiskStatus,
  StrategySignal,
} from "@/lib/contracts/snapshots";
import type { RiskPolicy, RiskState } from "@/lib/domain/risk";
import { analyzeMarketContext } from "@/lib/analysis";
import { evaluateRiskState, defaultRiskPolicy } from "@/lib/risk";
import {
  toMarketContextReadModel,
  toRiskStatusReadModel,
} from "@/lib/contracts/projections";
import { mockCandles } from "@/lib/mock/candles";

const now = () => new Date();

function isoMinutesAgo(minutes: number): string {
  return new Date(now().getTime() - minutes * 60_000).toISOString();
}

export function mockAccount(): AccountSummary {
  return {
    accountId: "account-001",
    label: "FTMO Challenge 100k",
    broker: "FTMO-Demo",
    currency: "USD",
    balance: 101_240.5,
    equity: 101_512.3,
    dailyPnl: 271.8,
    dailyDrawdownPercent: 0.9,
    totalDrawdownPercent: 2.4,
    openRiskPercent: 1.0,
  };
}

export function mockPositions(): Position[] {
  return [
    {
      positionId: "pos-001",
      accountId: "account-001",
      symbol: "XAUUSD",
      side: "buy",
      volume: 0.2,
      entryPrice: 3308.4,
      currentPrice: 3312.1,
      stopLoss: 3295.0,
      takeProfit: 3335.0,
      unrealizedPnl: 74.0,
      rMultiple: 0.28,
      strategyId: "ict-silver-bullet-v1",
      openedAt: isoMinutesAgo(42),
    },
    {
      positionId: "pos-002",
      accountId: "account-001",
      symbol: "XAUUSD",
      side: "buy",
      volume: 0.1,
      entryPrice: 3310.9,
      currentPrice: 3312.1,
      stopLoss: 3301.5,
      takeProfit: 3329.0,
      unrealizedPnl: 12.0,
      rMultiple: 0.13,
      strategyId: "ict-fvg-continuation-v1",
      openedAt: isoMinutesAgo(15),
    },
  ];
}

/**
 * Risk is now COMPUTED by the Phase 06 risk engine from the mock account +
 * positions + a default FTMO-style policy. Exposed as the domain RiskState +
 * policy so the mock client can both render the panel AND review signals
 * against the same state (Signal → Risk Review, Phase 07).
 */
export function mockRiskContext(): { state: RiskState; policy: RiskPolicy; balance: number } {
  const account = mockAccount();
  const policy = defaultRiskPolicy(account.accountId);
  const positions = mockPositions().map((p) => ({
    symbol: p.symbol,
    entryPrice: p.entryPrice,
    stopLoss: p.stopLoss,
    volume: p.volume,
  }));
  const state = evaluateRiskState({
    policy,
    initialBalance: 100_000,
    dayStartEquity: 102_400, // ~0.9% intraday loss vs current equity
    equity: account.equity,
    balance: account.balance,
    positions,
    tradesToday: 3,
    consecutiveLosses: 1,
    spreadPoints: 21,
    // NY AM window open so the Signal → Risk Review flow actually approves &
    // sizes (a blocked session gate would reject every mock signal).
    session: "new_york_am",
    sessionTradingEnabled: true,
    now: new Date().toISOString(),
  });
  return { state, policy, balance: account.balance };
}

export function mockRisk(): RiskStatus {
  const { state, policy } = mockRiskContext();
  return toRiskStatusReadModel(state, policy);
}

/**
 * Market context is now COMPUTED by the ICT/SMC engine (Phase 04) from a
 * deterministic synthetic candle series, then projected to the panel read
 * model — no longer hand-written. The data is still mock (synthetic candles),
 * but the analysis is real.
 */
export function mockMarketContext(): MarketContext {
  const state = analyzeMarketContext({
    symbol: "XAUUSD",
    timeframe: "M15",
    candles: mockCandles(),
  });
  return toMarketContextReadModel(state);
}

export function mockSignals(): StrategySignal[] {
  return [
    {
      signalId: "sig-014",
      symbol: "XAUUSD",
      strategyId: "ict-silver-bullet-v1",
      side: "buy",
      status: "reported",
      entryPrice: 3308.4,
      stopLoss: 3303.4,
      takeProfit: 3318.4,
      score: 8,
      maxScore: 10,
      contextSummary: "Sweep + MSS + M5 FVG retrace in NY AM window",
      riskDecision: "Approved: 0.05 lot at 1% risk",
      expiresAt: isoMinutesAgo(1),
      createdAt: isoMinutesAgo(2),
    },
    {
      signalId: "sig-013",
      symbol: "XAUUSD",
      strategyId: "ict-fvg-continuation-v1",
      side: "buy",
      status: "reported",
      entryPrice: 3310.9,
      stopLoss: 3305.9,
      takeProfit: 3320.9,
      score: 7,
      maxScore: 10,
      contextSummary: "H1 continuation from OB, aligned bias",
      riskDecision: "approved (risk-approval-021)",
      expiresAt: isoMinutesAgo(10),
      createdAt: isoMinutesAgo(18),
    },
    {
      signalId: "sig-012",
      symbol: "XAUUSD",
      strategyId: "ict-silver-bullet-v1",
      side: "sell",
      status: "rejected",
      entryPrice: 3316.2,
      stopLoss: 3321.2,
      takeProfit: 3306.2,
      score: 5,
      maxScore: 10,
      contextSummary: "Counter-bias sweep, low score",
      riskDecision: "rejected: score below threshold",
      expiresAt: isoMinutesAgo(30),
      createdAt: isoMinutesAgo(35),
    },
  ];
}

export function mockAgents(): AgentStatus[] {
  return [
    {
      agentId: "mt5-agent-001",
      accountId: "account-001",
      platform: "MT5",
      state: "connected",
      latencyMs: 38,
      lastHeartbeatAt: isoMinutesAgo(0),
      version: "0.1.0-mock",
    },
  ];
}

export function mockExecutionReports(): ExecutionReport[] {
  return [
    {
      reportId: "rep-034",
      commandId: "cmd-021",
      correlationId: "corr-sig-013",
      accountId: "account-001",
      agentId: "mt5-agent-001",
      symbol: "XAUUSD",
      side: "buy",
      status: "filled",
      detail: "0.10 lot @ 3310.90, TRADE_RETCODE_DONE",
      reportedAt: isoMinutesAgo(15),
    },
    {
      reportId: "rep-033",
      commandId: "cmd-021",
      correlationId: "corr-sig-013",
      accountId: "account-001",
      agentId: "mt5-agent-001",
      symbol: "XAUUSD",
      side: "buy",
      status: "acknowledged",
      detail: "Command accepted by agent",
      reportedAt: isoMinutesAgo(16),
    },
    {
      reportId: "rep-032",
      commandId: "cmd-019",
      correlationId: "corr-sig-011",
      accountId: "account-001",
      agentId: "mt5-agent-001",
      symbol: "XAUUSD",
      side: "buy",
      status: "position_closed",
      detail: "Closed +0.8R at partial target",
      reportedAt: isoMinutesAgo(95),
    },
  ];
}

export function mockPnlCalendar(): PnlCalendarDay[] {
  const days: PnlCalendarDay[] = [];
  const today = now();
  for (let i = 34; i >= 0; i -= 1) {
    const d = new Date(today.getTime() - i * 86_400_000);
    const weekday = d.getUTCDay();
    if (weekday === 0 || weekday === 6) {
      continue;
    }
    // Stable pseudo-random from the date so the calendar doesn't flicker.
    const seed = Number(`${d.getUTCFullYear()}${d.getUTCMonth() + 1}${d.getUTCDate()}`);
    const wave = Math.sin(seed);
    const traded = Math.abs(Math.sin(seed * 3)) > 0.25;
    days.push({
      date: d.toISOString().slice(0, 10),
      pnl: traded ? Math.round(wave * 620) : 0,
      trades: traded ? Math.max(1, Math.round(Math.abs(wave) * 4)) : 0,
    });
  }
  return days;
}

export function mockAlerts(): CockpitAlert[] {
  return [
    {
      alertId: "alert-005",
      severity: "warning",
      message: "NY PM session entries are disabled by session filter",
      raisedAt: isoMinutesAgo(6),
    },
    {
      alertId: "alert-004",
      severity: "info",
      message: "Signal sig-014 entered risk review",
      raisedAt: isoMinutesAgo(2),
    },
  ];
}
