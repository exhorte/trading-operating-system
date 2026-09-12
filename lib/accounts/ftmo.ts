/**
 * FTMO account profiles (EA-04). Structured by challenge type and phase, as
 * required — not a flat 5%/10% pair. Every risk-limit value below is a
 * PLACEHOLDER pending the official FTMO rules for the challenge actually
 * subscribed to (marked `TODO(FTMO-rules)`); guessing publicly-known FTMO
 * percentages here would be exactly the kind of unverified number this
 * fiche was asked not to produce. Only the cost model is sourced today:
 * fiche S01, "À vérifier avant de coder" — FTMO ≈ 5 $/lot round trip.
 */

import type { AccountId } from "@/lib/domain/primitives";
import type { RiskPolicy } from "@/lib/domain/risk";
import type { CostModel } from "./types";

export type FtmoChallengeType = "1-step" | "2-step";
export type FtmoPhase = "challenge" | "verification" | "funded";

/**
 * TODO(FTMO-rules): every limit below is a placeholder — renseigner depuis
 * le règlement FTMO officiel du challenge réellement souscrit avant
 * d'enregistrer un compte FTMO dans lib/accounts/registry.ts. A 1-step
 * challenge and the "funded" phase (either type) do not have a
 * `verification` step; `phase` is accepted for all challenge types so the
 * caller doesn't need to special-case 1-step, but a 1-step `registry.ts`
 * entry should only ever use `"challenge"` or `"funded"`.
 */
export function ftmoRiskPolicy(accountId: AccountId, phase: FtmoPhase): RiskPolicy {
  // TODO(FTMO-rules): each phase may carry different real limits (funded
  // accounts often relax the daily-loss rule, for instance) — every branch
  // returns the same placeholder values today, pending the official rules.
  switch (phase) {
    case "challenge":
    case "verification":
    case "funded":
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
}

/** Sourced (fiche S01): FTMO commission ≈ 5 $/lot round trip. Expected
 *  spreads are left empty — S01's cost gate never uses this in place of a
 *  live read; it's for display once populated from log_spread.py's output. */
export const FTMO_COST_MODEL: CostModel = {
  commissionPerLotRoundTrip: 5,
  expectedSpreadBySymbol: {},
  costThreshold: 0.25,
};
