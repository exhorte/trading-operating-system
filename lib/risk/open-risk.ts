/**
 * Open-risk sizing. MVP uses the XAUUSD contract factor (1.00 price move on
 * 1.0 lot ≈ 100 USD, i.e. a 100 oz contract). Generalise via SymbolMetadata
 * (tickValue/contractSize) when multi-symbol lands.
 */

import type { OpenRiskPosition } from "./types";

/**
 * USD at risk on one position between entry and stop loss. A position without a
 * valid stop (sl <= 0) has undefined risk and is excluded (returns 0) rather
 * than producing a nonsensical |entry − 0| figure — such a position is itself a
 * policy violation (no trade without a stop) surfaced elsewhere, not here.
 */
export function positionRiskUsd(p: OpenRiskPosition): number {
  if (p.stopLoss <= 0) {
    return 0;
  }
  const stopDistance = Math.abs(p.entryPrice - p.stopLoss);
  return stopDistance * p.volume * 100;
}

/** Summed open risk across positions as a percent of balance. */
export function openRiskPercent(positions: OpenRiskPosition[], balance: number): number {
  if (balance <= 0) {
    return 0;
  }
  const total = positions.reduce((sum, p) => sum + positionRiskUsd(p), 0);
  return Math.round((total / balance) * 100 * 100) / 100;
}
