/**
 * Risk models: the FTMO-style policy (configured limits), the live risk
 * state (usage against those limits), and the decision attached to every
 * signal before execution. Risk is a first-class gate, not a strategy detail.
 * Vocabulary source: context/domain/risk_ftmo.md.
 */

import type {
  AccountId,
  RiskApprovalId,
  SignalId,
  UtcTimestamp,
} from "./primitives";

/** Configured, auditable risk limits for one trading account. */
export interface RiskPolicy {
  accountId: AccountId;
  /** Max loss allowed within one trading day, percent of initial balance. */
  dailyLossLimitPercent: number;
  /** Max total drawdown allowed, percent of initial balance. */
  maxDrawdownLimitPercent: number;
  /** Max risk allowed on a single trade, percent of balance. */
  maxRiskPerTradePercent: number;
  /** Max summed open risk across positions, percent of balance. */
  maxOpenRiskPercent: number;
  maxTradesPerDay: number;
  /** Consecutive losses that trigger a lockout. */
  maxConsecutiveLosses: number;
  /** Spread (in points) above which new entries are blocked. */
  maxSpreadPoints: number;
  /** Minutes around high-impact news during which entries are blocked. */
  newsBlackoutMinutes: number;
}

/** Overall risk posture derived from gate evaluation. */
export type RiskMode = "normal" | "warning" | "locked";

/** Result of evaluating one safety gate (daily loss, spread, session, …). */
export interface RiskGateResult {
  gateId: string;
  label: string;
  state: "open" | "blocked";
  /** Human-readable explanation for the audit trail and cockpit. */
  detail: string;
}

/** Live risk usage for one account, recomputed as equity and trades evolve. */
export interface RiskState {
  accountId: AccountId;
  mode: RiskMode;
  dailyLossUsedPercent: number;
  maxDrawdownUsedPercent: number;
  openRiskPercent: number;
  /** Null when the data source has no trade history (e.g. observe prototype). */
  tradesToday: number | null;
  /** Null when the data source has no trade history (e.g. observe prototype). */
  consecutiveLosses: number | null;
  /** Null unless mode is "locked". */
  lockoutReason: string | null;
  /** Null unless a lockout is active; when the lockout auto-clears. */
  lockoutUntil: UtcTimestamp | null;
  gates: RiskGateResult[];
  evaluatedAt: UtcTimestamp;
}

/** Risk engine verdict on a strategy signal, prior to any execution command. */
export interface RiskDecision {
  approvalId: RiskApprovalId;
  signalId: SignalId;
  accountId: AccountId;
  approved: boolean;
  /** Volume (lots) the risk engine sized for the trade; null when rejected. */
  approvedVolume: number | null;
  /** Gate results at decision time, kept for decision replay. */
  gates: RiskGateResult[];
  reason: string;
  decidedAt: UtcTimestamp;
}
