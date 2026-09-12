/**
 * Risk policy resolution (v0.1 -> EA-04). Percent limits are hypotheses, not
 * validated constraints. Vocabulary source: context/domain/risk_ftmo.md,
 * model: lib/domain/risk.ts.
 *
 * EA-04: `accountId` now actually matters. An account registered in
 * lib/accounts/registry.ts gets its own configured RiskPolicy (FTMO,
 * real, ...); every other accountId — every caller today, since the
 * registry starts empty — falls back to the same hardcoded values this
 * function always returned. Signature and behavior for existing callers
 * are unchanged.
 */

import type { AccountId } from "@/lib/domain/primitives";
import type { RiskPolicy } from "@/lib/domain/risk";
import {
  ACCOUNT_PROFILES,
  resolveAccountProfile,
  type AccountProfileRegistry,
} from "@/lib/accounts/registry";

export function defaultRiskPolicy(
  accountId: AccountId,
  registry: AccountProfileRegistry = ACCOUNT_PROFILES,
): RiskPolicy {
  const profile = resolveAccountProfile(registry, accountId);
  if (profile) {
    return profile.riskPolicy;
  }

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
    // T03: −30/+30 min around a whitelisted FRED release (was 15).
    newsBlackoutMinutes: 30,
  };
}

/** Usage fraction of a limit at/above which the posture escalates to "warning". */
export const WARNING_THRESHOLD = 0.6;
