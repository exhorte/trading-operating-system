/**
 * T07's compliance figures over an arbitrary set of trades — pure.
 *
 * Extracted from `useComplianceRate` on 2026-09-20 so the account analysis
 * screen reads the same numbers over its own date range instead of growing a
 * second implementation. The hook is now fetch + this; `/analyse` is its own
 * fetch + this.
 *
 * Judges nothing beyond what `evaluateTrade` already judges: this only
 * counts and groups.
 */

import { DEFAULT_SESSION_WINDOWS } from "@/lib/analysis/config";
import type { JournalTrade } from "@/lib/journal/types";
import { toCanonicalSymbol } from "@/lib/market/symbols/registry";
import { defaultRiskPolicy } from "@/lib/risk/policy";
import { complianceRate, evaluateTrade, type ComplianceTradeInput } from "./evaluate";
import type { LockoutWindow, Violation, ViolationType } from "./violations";

export interface ComplianceSummary {
  /** 0..1, or null when there is no account to resolve a policy against. */
  rate: number | null;
  tradeCount: number;
  /** Trades carrying at least one violation. */
  breachedCount: number;
  /** Occurrence count per violation type — the attribution axis. */
  byType: Record<ViolationType, number>;
  /** Per-trade detail, keyed by brokerPositionId. */
  byTrade: Map<string, Violation[]>;
}

export const EMPTY_BY_TYPE: Record<ViolationType, number> = {
  LOCKOUT_ACTIVE: 0,
  SESSION_WINDOW: 0,
  SIZE_POLICY: 0,
};

export function emptyComplianceSummary(): ComplianceSummary {
  return {
    rate: null,
    tradeCount: 0,
    breachedCount: 0,
    byType: { ...EMPTY_BY_TYPE },
    byTrade: new Map(),
  };
}

/**
 * `balance` is the *current* balance, an approximation of the balance at
 * trade time — no historical account snapshot table exists (T07 fiche,
 * Décision 2). Passing null disables the size check rather than guessing,
 * which is why SIZE_POLICY can legitimately read zero on a window where the
 * other two detectors fired.
 */
export function summarizeCompliance(
  accountId: string,
  trades: JournalTrade[],
  lockouts: LockoutWindow[],
  balance: number | null,
): ComplianceSummary {
  const policy = defaultRiskPolicy(accountId);
  const byTrade = new Map<string, Violation[]>();
  const violationsPerTrade: Violation[][] = [];

  for (const trade of trades) {
    const input: ComplianceTradeInput = {
      brokerPositionId: trade.brokerPositionId,
      symbol: toCanonicalSymbol(trade.symbol),
      openedAt: trade.openedAt,
      volume: trade.volume,
      entryPrice: trade.entryPrice,
      stopLoss: trade.stopLoss,
    };
    const violations = evaluateTrade(input, lockouts, DEFAULT_SESSION_WINDOWS, balance, policy);
    byTrade.set(trade.brokerPositionId, violations);
    violationsPerTrade.push(violations);
  }

  const byType = { ...EMPTY_BY_TYPE };
  for (const violations of violationsPerTrade) {
    for (const violation of violations) {
      byType[violation.type] += 1;
    }
  }

  return {
    rate: complianceRate(violationsPerTrade),
    tradeCount: violationsPerTrade.length,
    breachedCount: violationsPerTrade.filter((v) => v.length > 0).length,
    byType,
    byTrade,
  };
}
