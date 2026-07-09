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
  SignalStatus,
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

export interface StrategySignal {
  signalId: string;
  symbol: string;
  strategyId: string;
  side: Side;
  status: SignalStatus;
  /** Proposed levels the risk engine ruled on (never moves them). */
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
  score: number;
  maxScore: number;
  contextSummary: string;
  riskDecision: string | null;
  expiresAt: string;
  createdAt: string;
}

/** Audit-grade risk decision for the dashboard (from a domain RiskDecision). */
export interface RiskDecisionView {
  approvalId: string;
  signalId: string;
  accountId: string;
  approved: boolean;
  /** Sized volume (lots) when approved; null when rejected. */
  approvedVolume: number | null;
  reason: string;
  /** Gate results at decision time (for the audit trail). */
  gates: RiskGate[];
  decidedAt: string;
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
