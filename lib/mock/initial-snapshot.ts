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
} from "@/lib/contracts/snapshots";
import type { RiskPolicy, RiskState } from "@/lib/domain/risk";
import type { UpcomingRelease } from "@/lib/risk/news-calendar";
import { analyzeMarketContext } from "@/lib/analysis";
import { evaluateRiskState, defaultRiskPolicy } from "@/lib/risk";
import {
  toMarketContextReadModel,
  toRiskStatusReadModel,
} from "@/lib/contracts/projections";
import { mockCandles } from "@/lib/mock/candles";
import { ACTIVE_FTMO_CHALLENGE } from "@/lib/accounts/ftmo";

/**
 * The account the mock snapshot presents.
 *
 * Defaults to a placeholder that exists nowhere. Set
 * `NEXT_PUBLIC_MOCK_ACCOUNT_ID` in `.env.local` to a real account id and the
 * mock preview's HTTP-backed screens — `/journal`, `/positions`, `/analyse`,
 * the compliance badge — read that account's real rows, while the realtime
 * stream stays scripted. Without it those screens are permanently empty in
 * mock mode, which is what made the preview useless for working on them.
 *
 * Deliberately an environment variable and never a constant: `.claude/CLAUDE.md`
 * — « Aucun identifiant de compte n'est jamais demandé, stocké ou partagé ».
 * `.env*` is gitignored, so a real id cannot reach a commit; a hardcoded one
 * would.
 */
const MOCK_ACCOUNT_ID = process.env.NEXT_PUBLIC_MOCK_ACCOUNT_ID ?? "account-001";

/** True when the id above points at something real, which makes the account
 *  label a lie unless it says so — the equity and positions below stay
 *  scripted while the journal-side screens turn real. */
const IS_REAL_ACCOUNT = MOCK_ACCOUNT_ID !== "account-001";

/**
 * The mock account *is* the FTMO challenge this cockpit is configured for
 * (T12). It used to present itself as a 100k challenge while the configured
 * challenge is 10 000 $ — the account screen would then have reported a
 * profit target "reached" at +91 000 $. Every absolute figure below was
 * written for 100k and is scaled to the default size (a challenge saved from
 * Settings does not rescale the script — it is a fixture, not an account);
 * percentages (drawdown, open risk) are ratios and come out unchanged, so the
 * default mock state stays "Armé".
 */
const CHALLENGE_SIZE = ACTIVE_FTMO_CHALLENGE.accountSize;
const SCALE = CHALLENGE_SIZE / 100_000;

/** A 100k-account dollar figure, scaled and rounded to the cent. */
function usd(amountAt100k: number): number {
  return Math.round(amountAt100k * SCALE * 100) / 100;
}

/** A 100k-account lot size, scaled and kept on the 0.01 volume step. */
function lots(volumeAt100k: number): number {
  return Math.max(0.01, Math.round(volumeAt100k * SCALE * 100) / 100);
}

const now = () => new Date();

function isoMinutesAgo(minutes: number): string {
  return new Date(now().getTime() - minutes * 60_000).toISOString();
}

export function mockAccount(): AccountSummary {
  return {
    accountId: MOCK_ACCOUNT_ID,
    label: IS_REAL_ACCOUNT
      ? "Compte réel — flux simulé"
      : `FTMO Challenge ${CHALLENGE_SIZE / 1000}k`,
    broker: IS_REAL_ACCOUNT ? "override .env.local" : "FTMO-Demo",
    currency: "USD",
    balance: usd(101_240.5),
    equity: usd(101_512.3),
    dailyPnl: usd(271.8),
    dailyDrawdownPercent: 0.9,
    totalDrawdownPercent: 2.4,
    openRiskPercent: 1.0,
  };
}

export function mockPositions(): Position[] {
  return [
    {
      positionId: "pos-001",
      accountId: MOCK_ACCOUNT_ID,
      symbol: "XAUUSD",
      side: "buy",
      volume: lots(0.2),
      entryPrice: 3308.4,
      currentPrice: 3312.1,
      stopLoss: 3295.0,
      takeProfit: 3335.0,
      unrealizedPnl: usd(74.0),
      rMultiple: 0.28,
      strategyId: "ict-silver-bullet-v1",
      openedAt: isoMinutesAgo(42),
    },
    {
      positionId: "pos-002",
      accountId: MOCK_ACCOUNT_ID,
      symbol: "XAUUSD",
      side: "buy",
      volume: lots(0.1),
      entryPrice: 3310.9,
      currentPrice: 3312.1,
      stopLoss: 3301.5,
      takeProfit: 3329.0,
      unrealizedPnl: usd(12.0),
      rMultiple: 0.13,
      strategyId: "ict-fvg-continuation-v1",
      openedAt: isoMinutesAgo(15),
    },
  ];
}

/**
 * Rotating market/risk conditions so the Signal → Risk Review loop shows real
 * rejections too, not only approvals. The same state feeds the Risk panel and
 * the review, so what the cockpit shows always matches why a signal was
 * approved or rejected.
 */
export type MockRiskScenario = "normal" | "wide_spread" | "closed_session" | "news_blackout";

/** T03: a plausible upcoming FRED release, far enough out that the news gate
 *  stays open by default — the "news_blackout" scenario overrides this. */
export function mockUpcomingReleases(scenario: MockRiskScenario = "normal"): UpcomingRelease[] {
  if (scenario === "news_blackout") {
    return [{ releaseId: 10, label: "CPI US", scheduledAt: new Date(now().getTime() + 10 * 60_000).toISOString() }];
  }
  return [{ releaseId: 50, label: "NFP US", scheduledAt: new Date(now().getTime() + 3 * 60 * 60_000).toISOString() }];
}

/**
 * Risk is now COMPUTED by the Phase 06 risk engine from the mock account +
 * positions + a default FTMO-style policy. Exposed as the domain RiskState +
 * policy so the mock client can both render the panel AND review signals
 * against the same state (Signal → Risk Review, Phase 07).
 */
export function mockRiskContext(
  scenario: MockRiskScenario = "normal",
): { state: RiskState; policy: RiskPolicy; balance: number } {
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
    initialBalance: CHALLENGE_SIZE,
    dayStartEquity: usd(102_400), // ~0.9% intraday loss vs current equity
    equity: account.equity,
    balance: account.balance,
    positions,
    tradesToday: 3,
    consecutiveLosses: 1,
    // wide_spread: above the 40-pt policy limit → spread gate blocks entries.
    spreadPoints: scenario === "wide_spread" ? 55 : 21,
    agentConnected: true,
    // closed_session: NY PM disabled → session gate blocks entries.
    session: scenario === "closed_session" ? "new_york_pm" : "new_york_am",
    sessionTradingEnabled: scenario !== "closed_session",
    // news_blackout: a release inside the window → news gate blocks entries.
    upcomingReleases: mockUpcomingReleases(scenario),
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

export function mockAgents(): AgentStatus[] {
  return [
    {
      agentId: "mt5-agent-001",
      accountId: MOCK_ACCOUNT_ID,
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
      accountId: MOCK_ACCOUNT_ID,
      agentId: "mt5-agent-001",
      symbol: "XAUUSD",
      side: "buy",
      status: "filled",
      detail: `${lots(0.1).toFixed(2)} lot @ 3310.90, TRADE_RETCODE_DONE`,
      reportedAt: isoMinutesAgo(15),
    },
    {
      reportId: "rep-033",
      commandId: "cmd-021",
      correlationId: "corr-sig-013",
      accountId: MOCK_ACCOUNT_ID,
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
      accountId: MOCK_ACCOUNT_ID,
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
