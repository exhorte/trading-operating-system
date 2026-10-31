/**
 * How the Account screen speaks of an account and the rules that govern it.
 *
 * The core owns both: the registry says which account it is (provider, type, login), the rules ledger says which limits are in
 * force today. This module only phrases them — one label for the account, the capital its percentages are measured from and
 * where that capital comes from, what a limit means in money — so that every card and every panel says the same thing.
 */

import type { Account, AccountRules, FtmoChallenge, Provider } from "@/lib/api/generated";
import { formatMoney } from "@/lib/format";

export const PROVIDER_NAMES: Record<Provider, string> = { FTMO: "FTMO", EXNESS: "Exness" };

export const PHASE_LABELS: Record<FtmoChallenge["phase"], string> = {
  challenge: "Challenge",
  verification: "Vérification",
  funded: "Funded",
};

export const ACCOUNT_TYPE_LABELS: Record<Account["accountType"], string> = {
  DIRECT: "compte direct",
  PROP_CHALLENGE: "challenge",
  PROP_VERIFICATION: "vérification",
  PROP_FUNDED: "funded",
};

/** Same money format as every other figure in the cockpit, without cents — a capital is a round number. */
export function formatCapital(size: number): string {
  return formatMoney(size).replace(/\.00$/, "");
}

export interface AccountProfile {
  account: Account;
  /** The rules in force today (the ledger resolved against the trading day). */
  rules: AccountRules;
  /** How the profile reads in the interface, e.g. "FTMO · 2-Step 10 000 $ · Challenge". */
  label: string;
  /**
   * The balance every percentage limit is measured against, or null when none is fixed. Null keeps the risk engine's behaviour —
   * the balance when the account connected — and must be shown as such, never as a floor.
   */
  referenceBalance: number | null;
  /** Where `referenceBalance` comes from, in the trader's words. */
  referenceSource: string;
  /** The FTMO challenge in progress, or null for a direct account. */
  challenge: FtmoChallenge | null;
  dailyLossLimitPercent: number;
  maxDrawdownLimitPercent: number;
  /** What the daily limit is in money, or null without a reference. */
  dailyLossAmount: number | null;
  /** The balance below which the overall loss limit is breached, or null without a reference. */
  floor: number | null;
}

export function challengeLabel(challenge: FtmoChallenge): string {
  return `FTMO · ${challenge.type === "2-step" ? "2-Step" : "1-Step"} ${formatCapital(challenge.accountSize)} · ${PHASE_LABELS[challenge.phase]}`;
}

export function profileOf(account: Account, rules: AccountRules): AccountProfile {
  const drawdown = rules.riskProfile.drawdown;
  const challenge = rules.tradingRules.challenge;
  const reference = drawdown.referenceBalance;
  const label = challenge
    ? challengeLabel(challenge)
    : `${PROVIDER_NAMES[account.provider]} · ${ACCOUNT_TYPE_LABELS[account.accountType]}`;
  const referenceSource =
    reference === null
      ? "non fixée — solde au moment où le cockpit s'est connecté"
      : challenge
        ? `taille du challenge (${formatCapital(challenge.accountSize)}), fixe pour toute sa durée`
        : `capital de référence (${formatCapital(reference)}), fixé dans Settings`;
  return {
    account,
    rules,
    label,
    referenceBalance: reference,
    referenceSource,
    challenge,
    dailyLossLimitPercent: drawdown.dailyLossLimitPercent,
    maxDrawdownLimitPercent: drawdown.maxDrawdownLimitPercent,
    dailyLossAmount: reference === null ? null : (reference * drawdown.dailyLossLimitPercent) / 100,
    floor: reference === null ? null : reference - (reference * drawdown.maxDrawdownLimitPercent) / 100,
  };
}
