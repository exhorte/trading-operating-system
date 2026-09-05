/**
 * Engine-internal input types for the risk engine. Pure and portable; the
 * engine imports only lib/domain and its own siblings.
 */

import type { TradingSession, UtcTimestamp } from "@/lib/domain/primitives";
import type { RiskPolicy, UpcomingRelease } from "@/lib/domain/risk";

/** Minimal position shape needed to size open risk. */
export interface OpenRiskPosition {
  symbol: string;
  entryPrice: number;
  stopLoss: number;
  volume: number;
}

/**
 * Everything the evaluator needs. Fields that a data source may not provide
 * (e.g. the observe prototype has no trade history) are nullable — null means
 * "unknown", never zero-as-fact.
 */
export interface RiskEvaluationInput {
  policy: RiskPolicy;
  /** Denominator for percent limits (account starting balance). */
  initialBalance: number;
  /** Equity at the start of the trading day/session, for daily-loss. */
  dayStartEquity: number;
  equity: number;
  balance: number;
  positions: OpenRiskPosition[];
  /** null when the source has no trade history (observe prototype). */
  tradesToday: number | null;
  consecutiveLosses: number | null;
  /** Current spread in points; null when unknown. */
  spreadPoints: number | null;
  session: TradingSession;
  sessionTradingEnabled: boolean;
  /** T03: null means the FRED calendar cache is absent/stale — the news gate
   *  fails CLOSED on null, unlike every other nullable gate input here. */
  upcomingReleases: UpcomingRelease[] | null;
  now: UtcTimestamp;
}
