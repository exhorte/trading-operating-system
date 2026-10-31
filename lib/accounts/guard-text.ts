/**
 * The words for the anti-tilt guard (ADR 0007): when does a change to an account's rules take effect, and why not at once.
 *
 * The decision is the core's — at the instant of saving, from what it sees (every account's session, the live link to the
 * terminal). The reasons come back structured; this phrases them. Nothing here decides whether a change is deferred.
 */

import type { GuardReason, RuleVersionView, VersionStatus } from "@/lib/api/generated";

function plural(count: number, singular: string, pluralForm: string): string {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

export function describeGuardReason(reason: GuardReason): string {
  const account = reason.accountId ? ` sur le compte ${reason.accountId}` : "";
  const count = reason.count ?? 0;
  switch (reason.code) {
    case "no_live_account":
      return "Aucun compte n'est connecté : rien ne permet de vérifier qu'aucune position n'est ouverte.";
    case "open_positions":
      return `${plural(count, "position ouverte", "positions ouvertes")}${account}.`;
    case "trades_today":
      return `${plural(count, "trade ouvert", "trades ouverts")} depuis le début de la journée de trading${account}.`;
    case "active_lockout":
      return `Verrou actif${account}${reason.detail ? ` (${reason.detail})` : ""}.`;
    default:
      return `Raison non reconnue : ${reason.code}.`;
  }
}

/** The reasons as one sentence, in the order the core gave them. */
export function describeGuardReasons(reasons: readonly GuardReason[]): string {
  return reasons.map(describeGuardReason).join(" ");
}

export const VERSION_STATUS_LABELS: Record<VersionStatus, string> = {
  in_effect: "En vigueur",
  pending: "En attente",
  superseded: "Remplacé",
  cancelled: "Annulé",
};

/** What a saved version says about itself, in one line: applied at once, or kept for the next trading day — and why. */
export function describeApplication(version: Pick<RuleVersionView, "deferred" | "deferralReasons">): string {
  return version.deferred
    ? `reporté au jour de trading suivant : ${describeGuardReasons(version.deferralReasons)}`
    : "appliqué immédiatement";
}
