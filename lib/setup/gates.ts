/**
 * S01 step 8 — the two viability gates ("Portes de viabilité"):
 *
 *   c = round-trip cost / stop distance
 *   R_réel = (R_nominal - c) / (1 + c)
 *
 * Distinct from lib/risk/gates.ts, which evaluates FTMO-style safety gates
 * (news, session, drawdown) for the Risk Engine. This file's gates decide
 * whether a setup is even worth proposing; they never touch lib/risk/ and
 * never contour it — S01 "ne contourne aucune gate et n'en ajoute aucune de
 * son côté" refers to the Risk Engine's own gates, not these.
 *
 * `spread` and `commission` must already be in the same price units as
 * `stopDistance` (e.g. price points, not pips or account currency) — S01's
 * formula is a pure ratio of price distances.
 */

export interface ViabilityGateInput {
  entryPrice: number;
  stopDistance: number;
  targetPrice: number;
  side: "buy" | "sell";
  /** Live spread at decision time, price units — read live, never averaged. */
  spread: number;
  /** Round-trip commission, price units. */
  commission: number;
  /** Provisional default 0.25 (S01) until the account profile (EA-04) supplies it. */
  costThreshold: number;
  /** Provisional default 3 (S01: at least 1:3). */
  minRiskReward: number;
}

export interface ViabilityGateResult {
  costRatio: number;
  riskRewardRatio: number;
  passed: boolean;
  reason: string | null;
}

export function evaluateViabilityGates(input: ViabilityGateInput): ViabilityGateResult {
  const roundTripCost = input.spread + input.commission;
  const costRatio = roundTripCost / input.stopDistance;

  if (costRatio > input.costThreshold) {
    return {
      costRatio,
      riskRewardRatio: 0,
      passed: false,
      reason: `porte de coût: c=${costRatio.toFixed(3)} > seuil ${input.costThreshold}`,
    };
  }

  const targetDistance = Math.abs(input.targetPrice - input.entryPrice);
  const rNominal = targetDistance / input.stopDistance;
  const rReal = (rNominal - costRatio) / (1 + costRatio);

  if (rReal < input.minRiskReward) {
    return {
      costRatio,
      riskRewardRatio: rReal,
      passed: false,
      reason: `porte R:R: ${rReal.toFixed(2)} < ${input.minRiskReward}`,
    };
  }

  return { costRatio, riskRewardRatio: rReal, passed: true, reason: null };
}
