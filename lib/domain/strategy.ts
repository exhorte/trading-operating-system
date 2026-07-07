/**
 * Strategy models: the signal lifecycle from detection to execution report.
 * A signal never reaches an execution agent without a RiskDecision — the
 * status union encodes that pipeline explicitly.
 */

import type { MarketContextState } from "./analysis";
import type {
  AccountId,
  RiskApprovalId,
  Side,
  SignalId,
  StrategyId,
  SymbolCode,
  UtcTimestamp,
} from "./primitives";

/**
 * Signal pipeline: detected → scored → risk_review → approved/rejected →
 * commanded → acknowledged → reported; expired can occur any time before
 * commanded.
 */
export type SignalStatus =
  | "detected"
  | "scored"
  | "risk_review"
  | "approved"
  | "rejected"
  | "commanded"
  | "acknowledged"
  | "reported"
  | "expired";

/** A tradeable setup emitted by a strategy engine for one account. */
export interface StrategySignal {
  signalId: SignalId;
  strategyId: StrategyId;
  accountId: AccountId;
  symbol: SymbolCode;
  side: Side;
  status: SignalStatus;
  /** Proposed levels; the risk engine may refuse or resize, never move them. */
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
  /** Confluence score inherited from the market context evaluation. */
  score: number;
  maxScore: number;
  /** Frozen analysis snapshot that justified the signal (explainability). */
  marketContext: MarketContextState;
  /** Null until the risk engine has ruled on the signal. */
  riskApprovalId: RiskApprovalId | null;
  createdAt: UtcTimestamp;
  /** Signal is void after this time; agents must refuse late commands. */
  expiresAt: UtcTimestamp;
}
