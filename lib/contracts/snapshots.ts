/**
 * Dashboard read models: the "latest known state" each cockpit panel renders.
 * Snapshots arrive on connect/resync, then realtime events mutate them.
 * See context/realtime/dashboard_realtime_model.md (snapshot + events pattern).
 */

import type {
  AgentState,
  Bias,
  ExecutionReportStatus,
  RiskState,
  Side,
  TradingSession,
} from "./enums";

export interface AccountSummary {
  accountId: string;
  label: string;
  broker: string;
  currency: string;
  balance: number;
  equity: number;
  dailyPnl: number;
  dailyDrawdownPercent: number;
  totalDrawdownPercent: number;
  openRiskPercent: number;
  // --- I2 (2026-09-26): MT5's account window — null/absent from an observer
  //     older than I2 or the mock source. Never the holder's name.
  margin?: number | null;
  freeMargin?: number | null;
  marginLevel?: number | null;
  server?: string | null;
  tradeMode?: "demo" | "contest" | "real" | "unknown" | null;
  leverage?: number | null;
  marginMode?: "hedging" | "netting" | "exchange" | "unknown" | null;
  fifoClose?: boolean | null;
  tradeAllowed?: boolean | null;
  tradeExpert?: boolean | null;
}

/**
 * I2: the EA-05 execution agent as it describes itself (C# Mt5AgentStatus) —
 * its hello overlaid by its latest heartbeat. Null fields: an agent older
 * than I1. Never carries the agent token.
 */
export interface ExecutionAgentStatus {
  accountId: string;
  agentId: string;
  agentVersion: string;
  buildId: string | null;
  /** Effective mode. */
  mode: "observe" | "paper" | "confirm";
  /** The highest mode this build may ever run in. */
  modeCeiling: "observe" | "paper" | "confirm" | null;
  /** "ok", or why the agent refuses every command. */
  identity: "ok" | "mismatch" | "no_account" | null;
  expectedAccountId: string | null;
  server: string;
  tradeMode: string | null;
  marginMode: string | null;
  fifoClose: boolean | null;
  terminalTradeAllowed: boolean | null;
  expertTradeAllowed: boolean | null;
  accountTradeExpert: boolean | null;
  accountTradeAllowed: boolean | null;
  tradable: boolean | null;
  closable: boolean | null;
  halted: boolean | null;
  /** Every OTHER expert attached in the terminal — Algo Trading arms them all. */
  attachedExperts: string[];
  gatewaySilentMs: number | null;
  lastHeartbeatTime: number | null;
}

export interface Position {
  positionId: string;
  accountId: string;
  symbol: string;
  side: Side;
  volume: number;
  entryPrice: number;
  currentPrice: number;
  stopLoss: number;
  takeProfit: number;
  unrealizedPnl: number;
  rMultiple: number;
  strategyId: string;
  openedAt: string;
}

export interface RiskGate {
  gateId: string;
  label: string;
  state: "open" | "blocked";
  detail: string;
}

export interface RiskStatus {
  state: RiskState;
  dailyLossLimitPercent: number;
  dailyLossUsedPercent: number;
  maxDrawdownLimitPercent: number;
  maxDrawdownUsedPercent: number;
  maxTradesPerDay: number;
  /** Null when the data source has no trade history (e.g. observe prototype). */
  tradesToday: number | null;
  /** Null when the data source has no trade history (e.g. observe prototype). */
  consecutiveLosses: number | null;
  lockoutReason: string | null;
  /** T02a: null unless mode is "locked" AND the lockout auto-expires (T02b's
   *  pause) — null for a manual/next-day-clearance lock too. */
  lockoutUntil: string | null;
  gates: RiskGate[];
}

export interface ScoreComponent {
  label: string;
  score: number;
  maxScore: number;
}

export interface MarketContext {
  symbol: string;
  timeframe: string;
  bias: Bias;
  structureState: string;
  lastStructureEvent: string;
  session: TradingSession;
  liquidityNote: string;
  pdArrayNote: string;
  score: number;
  maxScore: number;
  scoreBreakdown: ScoreComponent[];
  updatedAt: string;
}

export interface AgentStatus {
  agentId: string;
  accountId: string;
  platform: string;
  state: AgentState;
  latencyMs: number;
  lastHeartbeatAt: string;
  version: string;
}

export interface ExecutionReport {
  reportId: string;
  commandId: string;
  correlationId: string;
  accountId: string;
  agentId: string;
  symbol: string;
  side: Side;
  status: ExecutionReportStatus;
  detail: string;
  reportedAt: string;
}

export interface PnlCalendarDay {
  date: string;
  pnl: number;
  trades: number;
}

export interface CockpitAlert {
  alertId: string;
  severity: "info" | "warning" | "critical";
  message: string;
  raisedAt: string;
}
