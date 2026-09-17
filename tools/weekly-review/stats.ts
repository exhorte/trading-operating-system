/**
 * T08 — pure computation over a week's trades: the numbers the review
 * document reports, kept separate from fetching and rendering so they can
 * be eyeballed against the database by hand (fiche, incrément 1: verify
 * the numbers before styling the output).
 */

import { evaluateTrade, complianceRate, type ComplianceTradeInput } from "@/lib/compliance/evaluate";
import type { LockoutWindow, Violation } from "@/lib/compliance/violations";
import { defaultRiskPolicy } from "@/lib/risk/policy";
import { toCanonicalSymbol } from "@/lib/market/symbols/registry";
import { DEFAULT_SESSION_WINDOWS } from "@/lib/analysis/config";

/** Shape of GET /api/journal/trades (JournalRepository.GetTradesAsync). */
export interface JournalTrade {
  brokerPositionId: string;
  symbol: string;
  side: string;
  volume: number;
  entryPrice: number | null;
  exitPrice: number;
  realizedPnl: number;
  stopLoss: number | null;
  openedAt: string | null;
  closedAt: string;
  hasCapture: boolean;
}

export interface SymbolBreakdown {
  symbol: string;
  count: number;
  netRealizedPnl: number;
}

export interface ViolationTally {
  type: Violation["type"];
  count: number;
}

export interface WorstTrade {
  brokerPositionId: string;
  symbol: string;
  side: string;
  realizedPnl: number;
  closedAt: string;
  hasCapture: boolean;
}

export interface WeeklyStats {
  weekStartUtc: string;
  weekEndUtc: string;
  tradeCount: number;
  netRealizedPnl: number;
  bySymbol: SymbolBreakdown[];
  complianceRate: number;
  topViolationTypes: ViolationTally[];
  worstTrades: WorstTrade[];
}

/**
 * accountId is the only thing this function can't derive from trades/
 * lockouts alone (defaultRiskPolicy needs it) — balance is null (fiche
 * T15/T07 Décision: current balance isn't available outside the live
 * SignalR stream), so size-outside-policy never appears in
 * topViolationTypes here, same graceful degradation as T15's
 * get_compliance_violations.
 */
export function computeWeeklyStats(
  accountId: string,
  weekStartUtc: string,
  weekEndUtc: string,
  trades: JournalTrade[],
  lockouts: LockoutWindow[],
): WeeklyStats {
  const netRealizedPnl = trades.reduce((sum, t) => sum + t.realizedPnl, 0);

  const bySymbolMap = new Map<string, SymbolBreakdown>();
  for (const t of trades) {
    const existing = bySymbolMap.get(t.symbol);
    if (existing) {
      existing.count += 1;
      existing.netRealizedPnl += t.realizedPnl;
    } else {
      bySymbolMap.set(t.symbol, { symbol: t.symbol, count: 1, netRealizedPnl: t.realizedPnl });
    }
  }

  const policy = defaultRiskPolicy(accountId);
  const violationsPerTrade = trades.map((t) => {
    const input: ComplianceTradeInput = {
      brokerPositionId: t.brokerPositionId,
      symbol: toCanonicalSymbol(t.symbol),
      openedAt: t.openedAt,
      volume: t.volume,
      entryPrice: t.entryPrice,
      stopLoss: t.stopLoss,
    };
    return evaluateTrade(input, lockouts, DEFAULT_SESSION_WINDOWS, null, policy);
  });

  const violationCounts = new Map<Violation["type"], number>();
  for (const violations of violationsPerTrade) {
    for (const v of violations) {
      violationCounts.set(v.type, (violationCounts.get(v.type) ?? 0) + 1);
    }
  }
  const topViolationTypes = Array.from(violationCounts.entries())
    .map(([type, count]) => ({ type, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 3);

  const worstTrades = [...trades]
    .sort((a, b) => a.realizedPnl - b.realizedPnl)
    .slice(0, 3)
    .map((t) => ({
      brokerPositionId: t.brokerPositionId,
      symbol: t.symbol,
      side: t.side,
      realizedPnl: t.realizedPnl,
      closedAt: t.closedAt,
      hasCapture: t.hasCapture,
    }));

  return {
    weekStartUtc,
    weekEndUtc,
    tradeCount: trades.length,
    netRealizedPnl,
    bySymbol: Array.from(bySymbolMap.values()).sort((a, b) => b.count - a.count),
    complianceRate: complianceRate(violationsPerTrade),
    topViolationTypes,
    worstTrades,
  };
}
