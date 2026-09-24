/**
 * FTMO account profiles (EA-04, sourced by T12).
 *
 * Structured by challenge type and phase, not as a flat 5%/10% pair. The
 * values for the **2-Step Challenge phase** are no longer placeholders: they
 * come from the trader's own FTMO MetriX exports
 * (`05_screenchot/`, account 511333949, 2-Step, 10 000 $), whose
 * "Objectifs" table reads:
 *
 *   4 jours de Trading Minimum · Perte Maximum Journalière −500 $ ·
 *   Perte Max −1 000 $ · Objectif de Profit 1 000 $
 *
 * i.e. 5 % daily and 10 % overall of the initial account size, and a 10 %
 * profit target. Verification and Funded were never shown in those exports,
 * so they stay `TODO(FTMO-rules)` — guessing them from public material is
 * exactly what EA-04 refused to do.
 *
 * The cost model is sourced separately (fiche S01): ≈ 5 $/lot round trip.
 */

import type { AccountId } from "@/lib/domain/primitives";
import type { RiskPolicy } from "@/lib/domain/risk";
import type { CostModel } from "./types";

export type FtmoChallengeType = "1-step" | "2-step";
export type FtmoPhase = "challenge" | "verification" | "funded";

/** The challenge being traded right now — the only FTMO configuration that
 *  varies between challenges. */
export interface FtmoChallenge {
  type: FtmoChallengeType;
  /** Initial account size in account currency. Every FTMO limit is a
   *  percentage of this number, never of the current balance. */
  accountSize: number;
  phase: FtmoPhase;
}

/**
 * The default challenge (T12, décision 2 — gabarit 2-Step 10 000 $, phase
 * Challenge): what applies until the Settings screen's ledger holds an FTMO
 * version (T12 incrément 2, `settings.ts`).
 *
 * A new challenge or a passed phase is now recorded from Settings rather than
 * by a commit — under the anti-tilt rule the backend enforces when the change
 * is written (AccountSettingsGuard): at once only if no session is in
 * progress, otherwise from the next trading day. A limit that can be loosened
 * by a click in the middle of a session is not a limit (ADR 0007); one that
 * waits for tomorrow still is. The ledger is the record of which challenge
 * was traded when.
 */
export const ACTIVE_FTMO_CHALLENGE: FtmoChallenge = {
  type: "2-step",
  accountSize: 10_000,
  phase: "challenge",
};

/** What a phase requires of the trader beyond staying inside the limits. */
export interface FtmoObjectives {
  /** Minimum number of distinct trading days, or null when the phase has none. */
  minTradingDays: number | null;
  /** Profit target as a percentage of the account size, or null (funded). */
  profitTargetPercent: number | null;
}

/**
 * Sourced for the 2-Step Challenge phase (MetriX, see header). Every other
 * combination is `TODO(FTMO-rules)`: it returns nulls, which the objectives
 * screen renders as "non sourcé" instead of inventing a target.
 */
export function ftmoObjectives(challenge: FtmoChallenge): FtmoObjectives {
  if (challenge.type === "2-step" && challenge.phase === "challenge") {
    return { minTradingDays: 4, profitTargetPercent: 10 };
  }
  // TODO(FTMO-rules): verification, funded and 1-step — not in the exports.
  return { minTradingDays: null, profitTargetPercent: null };
}

/**
 * Daily and overall loss limits are sourced for the 2-Step Challenge phase
 * (−500 $ and −1 000 $ on 10 000 $). The remaining fields are this
 * system's own discipline limits, identical across every profile — FTMO does
 * not dictate risk per trade or trades per day.
 *
 * TODO(FTMO-rules): verification and funded may carry different loss limits;
 * every phase returns the challenge values until a source says otherwise.
 */
export function ftmoRiskPolicy(accountId: AccountId, phase: FtmoPhase): RiskPolicy {
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
