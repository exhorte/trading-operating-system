/**
 * Connecting an account from its broker identifiers (ADR 0013, 0020) — the part that is arithmetic and rules, kept out of
 * the component so it can be tested without a browser.
 *
 * The core reads the account at the broker (`accounts_discover`) and answers with facts; this module turns the facts and the
 * trader's few decisions into the registration the core will accept, and says in words why it cannot yet. The core re-checks
 * everything and has the last word: nothing here is a guard, only a courtesy before the click.
 *
 * Nothing here ever sees a password: it is read from the field by the component, sent once, and cleared.
 */

import type { AccountType, CreateAccountRequest, DiscoveredAccount, Environment, Provider } from "@/lib/api/generated";
import { PROVIDER_NAMES } from "@/lib/accounts/profile";

/** Whose rules the account follows: its broker's own, or — on a demo only — FTMO's, to rehearse them (ADR 0020). */
export type RulesProfile = "own" | "ftmo";

export interface Wanted {
  provider: Provider;
  rules: RulesProfile;
}

/** What the trader decides after reading the broker's facts. */
export interface Review {
  name: string;
  /** The initial capital, as typed — a broker states a balance, never what the account was funded with. */
  capital: string;
  /** Explicit: the grid of risk is measured against this figure, so it is never taken silently. */
  capitalConfirmed: boolean;
  environment: Environment;
}

const number = (text: string): number => Number(text.trim().replace(/\s/g, "").replace(",", "."));

/** FTMO's rules (a challenge) apply to a FTMO account, and to a demo that rehearses them. */
export function followsFtmo(wanted: Wanted): boolean {
  return wanted.provider === "FTMO" || wanted.rules === "ftmo";
}

export function accountTypeFor(wanted: Wanted): AccountType {
  return followsFtmo(wanted) ? "PROP_CHALLENGE" : "DIRECT";
}

/** What the review starts from: the broker's own figures, the capital proposal included — still to be confirmed. */
export function reviewOf(found: DiscoveredAccount): Review {
  return {
    name: found.suggestedName,
    capital: String(found.capital.amount),
    capitalConfirmed: false,
    environment: found.environment ?? "DEMO",
  };
}

/** Why this reading cannot be registered as asked, in the trader's words. Empty = it can. */
export function blockers(found: DiscoveredAccount, wanted: Wanted, review: Review): string[] {
  const found_: string[] = [];
  if (found.provider !== null && found.provider !== wanted.provider) {
    found_.push(
      `Ce serveur (${found.server}) est celui de ${PROVIDER_NAMES[found.provider]}, pas de ${PROVIDER_NAMES[wanted.provider]} : change de fournisseur.`,
    );
  }
  if (wanted.provider === "EXNESS" && wanted.rules === "ftmo" && review.environment !== "DEMO") {
    found_.push("Le profil FTMO ne se répète que sur un compte démo : un compte réel suit les règles de son courtier.");
  }
  if (review.name.trim() === "" || review.name.trim().length > 80) {
    found_.push("Le nom doit faire de 1 à 80 caractères.");
  }
  const capital = number(review.capital);
  const [low, high] = followsFtmo(wanted) ? [1_000, 10_000_000] : [1, 100_000_000];
  if (!Number.isFinite(capital) || capital < low || capital > high) {
    found_.push(`Le capital initial doit être compris entre ${low.toLocaleString("fr-FR")} et ${high.toLocaleString("fr-FR")}.`);
  } else if (!review.capitalConfirmed) {
    found_.push("Confirme le capital initial : les limites de risque se mesurent contre lui, jamais contre le solde du jour.");
  }
  return found_;
}

/** The registration the core accepts. Call only when `blockers` is empty. */
export function registrationFor(found: DiscoveredAccount, wanted: Wanted, review: Review): CreateAccountRequest {
  const capital = number(review.capital);
  const rehearsing = wanted.provider === "EXNESS" && wanted.rules === "ftmo";
  return {
    name: review.name.trim(),
    provider: wanted.provider,
    accountType: accountTypeFor(wanted),
    login: found.login,
    server: found.server,
    currency: found.currency,
    environment: review.environment,
    terminalPath: found.terminalPath,
    symbolSuffix: found.symbolSuffix,
    ...(followsFtmo(wanted)
      ? { challenge: { type: "2-step" as const, accountSize: capital, phase: "challenge" as const } }
      : { referenceBalance: capital }),
    rulesProfile: rehearsing ? "FTMO" : null,
  };
}

/** The login the trader typed, as the core wants it (a positive integer), or null. */
export function loginOf(text: string): number | null {
  const value = number(text);
  return Number.isInteger(value) && value > 0 ? value : null;
}
