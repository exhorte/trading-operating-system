/**
 * « Fermer toutes les positions » (ADR 0034) — what the dialog says, as pure functions so that every sentence is tested.
 *
 * The core derives the whole picture (a batch is its commands plus the broker's last picture); this file only turns it into the
 * words the trader reads. The rule that governs every line below: nothing is called « fermé » until the core says CONFIRMED, and
 * the whole is not « terminée » until the core says COMPLETE — MT5 agrees and a reconciliation has run since.
 */

import type {
  CloseAllAction,
  CloseAllItemStatus,
  CloseAllReason,
  CloseAllReport,
  CloseAllStatus,
} from "@/lib/api/generated";

/** The label of the confirm button, word for word: opening the dialog sends nothing, only this does. */
export const CONFIRM_LABEL = "CONFIRMER LA FERMETURE DE TOUTES LES POSITIONS";
export const BUTTON_LABEL = "FERMER TOUTES LES POSITIONS";
/** What the body must carry for the core to act (the core refuses anything else). */
export const CONFIRMATION = "CLOSE_ALL";

export const ITEM_LABELS: Record<CloseAllItemStatus, string> = {
  IN_PROGRESS: "En cours",
  VERIFYING: "Exécutée — vérification chez MT5",
  CONFIRMED: "Fermée — confirmée par MT5",
  ALREADY_CLOSED: "Déjà fermée",
  REJECTED: "Refusée",
  SIMULATED: "Simulée — rien n'a été fermé",
  UNKNOWN: "Inconnue — à réconcilier",
  MISMATCH: "Incohérence — MT5 la montre encore ouverte",
  NOT_CLOSABLE: "Non fermable par l'agent — à fermer dans MT5",
};

export type Tone = "profit" | "loss" | "warning" | "info" | "muted";

export function itemTone(status: CloseAllItemStatus): Tone {
  switch (status) {
    case "CONFIRMED":
    case "ALREADY_CLOSED":
      return "profit";
    case "IN_PROGRESS":
    case "VERIFYING":
      return "info";
    case "REJECTED":
    case "MISMATCH":
      return "loss";
    default:
      return "warning";
  }
}

const ACTIONS: Record<CloseAllAction, string> = {
  WAIT: "Patientez : des commandes sont encore en cours.",
  RECONCILE:
    "Une commande est dans le doute. Cliquez « Vérifier avec MT5 » : la réconciliation tranche. Ne la renvoyez jamais à la main.",
  CLOSE_IN_MT5: "Fermez les positions restantes directement dans MT5.",
  ENABLE_AGENT:
    "L'agent d'exécution simule seulement (compilé en OBSERVE, ou mode PAPER) : aucun ordre n'a atteint le courtier. Fermez dans MT5, ou recompilez l'agent en CONFIRM — c'est votre décision.",
  REVIEW_REJECTIONS: "Lisez les motifs de refus ci-dessous avant de relancer.",
  CHECK_MT5: "L'agent dit avoir fermé, MT5 montre encore la position : vérifiez dans MT5.",
  RERUN: "Des positions sont apparues après votre confirmation : elles n'ont pas été touchées. Relancez la fermeture pour les inclure.",
};

export function actionText(action: CloseAllAction): string {
  return ACTIONS[action];
}

const REASONS: Record<string, string> = {
  TARGET_NOT_OURS: "L'agent ne ferme que ce qu'il a placé lui-même (autre numéro magique).",
  LOGIN_NOT_CLOSABLE: "Ce compte n'est pas dans InpClosableLogins de l'agent : il refuse de fermer.",
  AGENT_UNREACHABLE: "Aucun agent d'exécution joignable : rien n'a été envoyé.",
  AGENT_CAPABILITY_MISSING: "L'agent n'annonce pas la capacité « close » (ou « cancel »).",
  POSITION_NOT_FOUND: "Position introuvable chez le courtier.",
  ORDER_NOT_FOUND: "Ordre en attente introuvable chez le courtier.",
  ACCOUNT_MISMATCH: "Le terminal est connecté à un autre compte que celui visé.",
  ACCOUNT_NOT_CONNECTED: "Le compte n'est pas connecté.",
  STORE_UNAVAILABLE: "Base indisponible : la commande n'a pas pu être enregistrée, donc pas envoyée.",
  DEAD_MAN: "L'agent n'entend plus le cœur (interrupteur d'homme mort).",
  IDENTITY_REFUSED: "L'agent refuse : identité du compte non conforme.",
  UNKNOWN: "Résultat inconnu : la commande reste à réconcilier, elle n'est jamais renvoyée.",
  SIMULATED: "Simulé : aucun ordre réel n'a été envoyé au courtier.",
  NOT_CLOSABLE: "Position non fermable par l'agent (placée à la main ou par un autre EA).",
  MISMATCH: "Exécutée selon l'agent, toujours ouverte selon MT5.",
};

export function reasonText(reason: string, detail = ""): string {
  const known = REASONS[reason];
  if (known) {
    return known;
  }
  return detail ? `${reason} — ${detail}` : reason;
}

const WARNINGS: Record<string, string> = {
  market_price:
    "Les positions seront fermées au prix disponible au moment où chaque ordre atteint le courtier : le résultat final peut différer du P&L latent affiché.",
  agent_simulates:
    "L'agent d'exécution n'est pas en mode CONFIRM : il validera les ordres mais n'en enverra aucun au courtier (SIMULATED). Rien ne sera fermé chez le courtier.",
  agent_cannot_cancel: "L'agent n'annonce pas « cancel » : l'annulation des ordres en attente serait refusée.",
  stale_snapshot: "Le terminal n'a pas pu être lu à l'instant : la liste peut ne pas être à jour.",
  foreign_positions:
    "Certaines positions n'ont pas été placées par l'agent d'exécution : il ne les fermera pas. Fermez-les dans MT5.",
  real_account: "COMPTE RÉEL — LES ORDRES PEUVENT ENTRAÎNER UNE PERTE FINANCIÈRE",
};

const BLOCKERS: Record<string, string> = {
  account_not_connected: "Le compte n'est pas connecté : rien ne peut être lu ni envoyé.",
  account_mismatch: "Le terminal est connecté à un autre compte que celui sélectionné.",
  no_agent: "Aucun agent d'exécution n'est connecté : rien ne peut être envoyé à MT5. Fermez dans MT5.",
  agent_refuses: "L'agent d'exécution refuse de recevoir des commandes.",
  agent_cannot_close: "L'agent n'annonce pas la capacité « close ».",
};

export function reasonLine(reason: CloseAllReason, kind: "warning" | "blocker"): string {
  const table = kind === "warning" ? WARNINGS : BLOCKERS;
  return table[reason.code] ?? reason.detail;
}

export function headline(status: CloseAllStatus): string {
  switch (status) {
    case "NOTHING_TO_CLOSE":
      return "Aucune position à fermer.";
    case "IN_PROGRESS":
      return "Fermeture en cours…";
    case "AWAITING_RECONCILIATION":
      return "Fermetures confirmées — réconciliation avec MT5 en cours…";
    case "COMPLETE":
      return "Toutes les positions sont fermées et réconciliées avec MT5.";
    case "INCOMPLETE":
      return "Fermeture incomplète — voir les motifs et l'action recommandée.";
  }
}

/** « 3 positions détectées · 1 fermeture confirmée · 1 en cours · 1 refusée » — only what is not zero. */
export function progressLine(report: CloseAllReport): string {
  const c = report.counts;
  const plural = (n: number, one: string, many: string) => `${n} ${n > 1 ? many : one}`;
  const parts = [plural(c.detected, "cible détectée", "cibles détectées")];
  if (c.confirmed) parts.push(plural(c.confirmed, "fermeture confirmée", "fermetures confirmées"));
  if (c.alreadyClosed) parts.push(plural(c.alreadyClosed, "déjà fermée", "déjà fermées"));
  if (c.inProgress) parts.push(`${c.inProgress} en cours`);
  if (c.verifying) parts.push(`${c.verifying} en vérification`);
  if (c.rejected) parts.push(plural(c.rejected, "refusée", "refusées"));
  if (c.unknown) parts.push(plural(c.unknown, "inconnue", "inconnues"));
  if (c.simulated) parts.push(plural(c.simulated, "simulée", "simulées"));
  if (c.mismatch) parts.push(plural(c.mismatch, "incohérence", "incohérences"));
  if (c.notClosable) parts.push(plural(c.notClosable, "non fermable par l'agent", "non fermables par l'agent"));
  return parts.join(" · ");
}

export interface Summary {
  closed: number;
  stillOpen: number;
  rejectedOrUnknown: number;
}

/** The three figures the final report must give: closed, still open, refused or unknown. */
export function summary(report: CloseAllReport): Summary {
  const c = report.counts;
  return {
    closed: c.confirmed + c.alreadyClosed,
    stillOpen: c.positionsStillOpen,
    rejectedOrUnknown: c.rejected + c.unknown + c.simulated + c.mismatch + c.notClosable,
  };
}

/** Whether the dialog should poll the core again, and whether it should ask the core to check with MT5 now. */
export function nextStep(report: CloseAllReport): "poll" | "verify" | "stop" {
  if (report.final) {
    return "stop";
  }
  const moving = report.items.some((i) => i.status === "IN_PROGRESS");
  return moving ? "poll" : "verify";
}
