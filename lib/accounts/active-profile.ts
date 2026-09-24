/**
 * The profile that applies to the account the cockpit is looking at (T12).
 *
 * One account at a time: whichever terminal the observer is attached to
 * decides (T12, décision 1). The firm is recognised from the broker name MT5
 * reports; no account number is involved. Multi-account resolution by
 * `accountId` is EA-04's registry, still empty, kept for T11.
 *
 * Since T12 incrément 2 the challenge, the Exness reference and the
 * recognition texts come from the settings in effect (`settings.ts`,
 * resolved from the ledger the Settings screen writes); the code's values
 * are the default until the ledger holds a version.
 */

import type { AccountId } from "@/lib/domain/primitives";
import { formatMoney } from "@/lib/format";
import type { RiskPolicy } from "@/lib/domain/risk";
import { detectFirm, type Firm } from "./firm";
import { FTMO_COST_MODEL, ftmoRiskPolicy, type FtmoChallenge } from "./ftmo";
import { REAL_COST_MODEL, realRiskPolicy } from "./real";
import { brokerMatchersOf, DEFAULT_ACCOUNT_SETTINGS, type AccountSettings } from "./settings";
import type { CostModel } from "./types";

export interface ActiveProfile {
  firm: Firm;
  /** How the profile reads in the interface, e.g. "FTMO · 2-Step 10 000 $ · Challenge". */
  label: string;
  riskPolicy: RiskPolicy;
  /**
   * The balance every percentage limit is measured against, or null when the
   * profile does not fix one. Null keeps the risk engine's previous
   * behaviour — the balance when the cockpit last connected — and must be
   * shown as such, never as a floor.
   */
  referenceBalance: number | null;
  /** Where `referenceBalance` comes from, in the trader's words. */
  referenceSource: string;
  costModel: CostModel;
  /** The FTMO challenge in progress, or null for a direct account. */
  challenge: FtmoChallenge | null;
}

const PHASE_LABELS: Record<FtmoChallenge["phase"], string> = {
  challenge: "Challenge",
  verification: "Vérification",
  funded: "Funded",
};

/** Same money format as every other figure in the cockpit, without cents —
 *  a challenge size is a round number. */
function formatSize(size: number): string {
  return formatMoney(size).replace(/\.00$/, "");
}

export function ftmoProfile(accountId: AccountId, challenge: FtmoChallenge): ActiveProfile {
  return {
    firm: "ftmo",
    label: `FTMO · ${challenge.type === "2-step" ? "2-Step" : "1-Step"} ${formatSize(challenge.accountSize)} · ${PHASE_LABELS[challenge.phase]}`,
    riskPolicy: ftmoRiskPolicy(accountId, challenge.phase),
    referenceBalance: challenge.accountSize,
    referenceSource: `taille du challenge (${formatSize(challenge.accountSize)}), fixe pour toute sa durée`,
    costModel: FTMO_COST_MODEL,
    challenge,
  };
}

export function exnessProfile(
  accountId: AccountId,
  referenceBalance: number | null,
): ActiveProfile {
  return {
    firm: "exness",
    label: "Exness · compte direct",
    riskPolicy: realRiskPolicy(accountId),
    referenceBalance,
    referenceSource:
      referenceBalance === null
        ? "non fixée — solde au moment où le cockpit s'est connecté"
        : `capital de référence (${formatSize(referenceBalance)}), fixé dans Settings`,
    costModel: REAL_COST_MODEL,
    challenge: null,
  };
}

/**
 * Null when the broker is not one this system knows: callers fall back to
 * `defaultRiskPolicy` and to the connection-time balance, which is the
 * behaviour every account had before T12.
 *
 * `settings` are the ones in effect (`resolveAccountSettings`); without them,
 * the code's defaults — the exact pre-incrément-2 behaviour.
 */
export function resolveActiveProfile(
  account: { accountId: AccountId; broker: string },
  settings: AccountSettings = DEFAULT_ACCOUNT_SETTINGS,
): ActiveProfile | null {
  switch (detectFirm(account.broker, brokerMatchersOf(settings))) {
    case "ftmo":
      return ftmoProfile(account.accountId, settings.ftmo.challenge);
    case "exness":
      return exnessProfile(account.accountId, settings.exness.referenceBalance);
    default:
      return null;
  }
}
