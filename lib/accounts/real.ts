/**
 * Real (non-prop) account profile. A prop firm's own daily-loss rule
 * disqualifies the challenge if breached — it is not a safety net for the
 * trader themselves. A real account has no such external rule, so its own
 * daily-loss limit is deliberately tighter than FTMO's. Values below are
 * PLACEHOLDERS, same discipline as ftmo.ts: `TODO(real-account-rules)`
 * before a real account is registered in lib/accounts/registry.ts.
 */

import type { AccountId } from "@/lib/domain/primitives";
import type { RiskPolicy } from "@/lib/domain/risk";
import type { CostModel } from "./types";

// TODO(real-account-rules): confirm against the actual broker/account terms
// before registering a real account.
export function realRiskPolicy(accountId: AccountId): RiskPolicy {
  return {
    accountId,
    dailyLossLimitPercent: 3,
    maxDrawdownLimitPercent: 8,
    maxRiskPerTradePercent: 1,
    maxOpenRiskPercent: 2,
    maxTradesPerDay: 6,
    maxConsecutiveLosses: 3,
    maxSpreadPoints: 40,
    newsBlackoutMinutes: 30,
  };
}

/** TODO(real-account-rules): Exness Raw/Pro commission differs from FTMO's —
 *  fiche S01 flags this explicitly ("le même setup peut passer sur l'un et
 *  être refusé sur l'autre"). 0 here is honest-absence, not a claim of a
 *  commission-free account. */
export const REAL_COST_MODEL: CostModel = {
  commissionPerLotRoundTrip: 0,
  expectedSpreadBySymbol: {},
  costThreshold: 0.25,
};
