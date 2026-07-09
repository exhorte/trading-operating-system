/**
 * Default FTMO-style risk policy (v0.1). Percent limits are account-agnostic;
 * every value is a hypothesis, not a validated constraint. Vocabulary source:
 * context/domain/risk_ftmo.md, model: lib/domain/risk.ts.
 */

import type { AccountId } from "@/lib/domain/primitives";
import type { RiskPolicy } from "@/lib/domain/risk";

export function defaultRiskPolicy(accountId: AccountId): RiskPolicy {
  return {
    accountId,
    dailyLossLimitPercent: 5,
    maxDrawdownLimitPercent: 10,
    maxRiskPerTradePercent: 1,
    maxOpenRiskPercent: 2,
    maxTradesPerDay: 6,
    maxConsecutiveLosses: 3,
    // XAUUSD points (1 point = 0.01), i.e. a 0.40 spread.
    maxSpreadPoints: 40,
    newsBlackoutMinutes: 15,
  };
}

/** Usage fraction of a limit at/above which the posture escalates to "warning". */
export const WARNING_THRESHOLD = 0.6;
