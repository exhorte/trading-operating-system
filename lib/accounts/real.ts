/**
 * Real (non-prop) account profile — Exness, traded directly.
 *
 * Limits: 5 % daily, 10 % overall — the same as FTMO, by the trader's own
 * decision (T12, 2026-09-21). The recommendation put to them was stricter
 * (3 %/8 %): a prop firm's daily-loss rule protects the firm by closing the
 * account, while nothing external closes a real account, so its own limit is
 * the only one there is. They chose parity with FTMO; applied as decided.
 */

import type { AccountId } from "@/lib/domain/primitives";
import type { RiskPolicy } from "@/lib/domain/risk";
import type { CostModel } from "./types";

export function realRiskPolicy(accountId: AccountId): RiskPolicy {
  return {
    accountId,
    dailyLossLimitPercent: 5,
    maxDrawdownLimitPercent: 10,
    maxRiskPerTradePercent: 1,
    maxOpenRiskPercent: 2,
    maxTradesPerDay: 6,
    maxConsecutiveLosses: 3,
    maxSpreadPoints: 40,
    newsBlackoutMinutes: 30,
  };
}

/**
 * The default for the balance a real account's overall loss is measured
 * from — the capital committed to trading. The trader sets it from the
 * Settings screen (T12 incrément 2, `settings.ts`); this is what applies
 * until they do.
 *
 * `null`, and `null` means the risk engine keeps its previous behaviour:
 * overall loss measured from the balance when the cockpit last connected.
 * `/account` says so rather than implying a fixed floor exists. A prop
 * challenge has an unambiguous reference (its size); a real account does
 * not, and choosing one is the trader's call, not a default.
 */
export const EXNESS_REFERENCE_BALANCE: number | null = null;

/** TODO(real-account-rules): Exness Raw/Pro commission differs from FTMO's —
 *  fiche S01 flags this explicitly ("le même setup peut passer sur l'un et
 *  être refusé sur l'autre"). 0 matches the Standard account measured in
 *  Phase 0 (`*m` symbols); it is not a claim about Raw or Pro. */
export const REAL_COST_MODEL: CostModel = {
  commissionPerLotRoundTrip: 0,
  expectedSpreadBySymbol: {},
  costThreshold: 0.25,
};
