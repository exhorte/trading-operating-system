/**
 * T07 — orchestrates the closed-taxonomy detectors (violations.ts) over one
 * trade, and reduces many trades' results to the single weekly compliance
 * curve the fiche's critère de réussite asks for. Kept separate from
 * violations.ts: that file is three independent pure questions, this file
 * is "how they combine for one trade and for a week" — a different, higher
 * concern, same split lib/setup/reconciliation.ts already uses for its own
 * pure/orchestration boundary.
 */

import type { SymbolCode } from "@/lib/domain/primitives";
import type { SessionWindow } from "@/lib/domain/market";
import type { RiskPolicy } from "@/lib/domain/risk";
import { symbolMetadata } from "@/lib/market/symbols/registry";
import {
  detectLockoutViolation,
  detectSessionViolation,
  detectSizeViolation,
  type LockoutWindow,
  type Violation,
} from "./violations";

export interface ComplianceTradeInput {
  brokerPositionId: string;
  /** Canonical (EURUSD/GBPUSD/XAUUSD), never the broker-form name
   *  (closed_trades.symbol is "EURUSDm" etc.) — the caller converts via
   *  lib/market/symbols/registry.ts::toCanonicalSymbol first (ADR 0004: no
   *  broker-specific name may leak into a domain module). Null when that
   *  conversion fails — lockout/session still get judged, only the
   *  symbol-dependent size check is skipped, never everything at once. */
  symbol: SymbolCode | null;
  openedAt: string | null;
  volume: number;
  entryPrice: number | null;
  stopLoss: number | null;
}

/**
 * All applicable violations for one trade. openedAt === null (no
 * position_opens row — T06 fiche's same honest-null case) means lockout and
 * session cannot be judged at all, not that they pass; this reflects that
 * as an empty result rather than a guessed pass, same as every other
 * "unknown, not compliant" distinction this codebase already draws.
 * `balance` null skips the size check the same way (fiche Décision 2's
 * approximation still needs SOME balance to compare against).
 */
export function evaluateTrade(
  trade: ComplianceTradeInput,
  lockouts: LockoutWindow[],
  sessionWindows: SessionWindow[],
  balance: number | null,
  policy: Pick<RiskPolicy, "maxRiskPerTradePercent">,
): Violation[] {
  if (trade.openedAt === null) {
    return [];
  }

  const violations: Violation[] = [];

  const lockoutViolation = detectLockoutViolation(trade.openedAt, lockouts);
  if (lockoutViolation) {
    violations.push(lockoutViolation);
  }

  const sessionViolation = detectSessionViolation(trade.openedAt, sessionWindows);
  if (sessionViolation) {
    violations.push(sessionViolation);
  }

  if (balance !== null && trade.symbol !== null && trade.entryPrice !== null && trade.stopLoss !== null) {
    const metadata = symbolMetadata(trade.symbol);
    if (metadata) {
      const sizeViolation = detectSizeViolation(
        trade.volume,
        trade.entryPrice,
        trade.stopLoss,
        balance,
        policy,
        metadata,
      );
      if (sizeViolation) {
        violations.push(sizeViolation);
      }
    }
  }

  return violations;
}

/** Trades with zero violations / total — 1 (fully compliant) on an empty
 *  week rather than 0, so a week with no trading doesn't read as a bad
 *  score; there was nothing to violate. */
export function complianceRate(violationsPerTrade: Violation[][]): number {
  if (violationsPerTrade.length === 0) {
    return 1;
  }
  const compliant = violationsPerTrade.filter((v) => v.length === 0).length;
  return compliant / violationsPerTrade.length;
}
