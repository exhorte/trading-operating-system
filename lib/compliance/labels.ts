import type { ViolationType } from "./violations";

/**
 * What each violation type is called in the interface.
 *
 * One place, because the discipline gauge and the account analysis screen
 * both name them and a violation that reads differently on two screens is a
 * violation the trader will treat as two different things.
 */
export const VIOLATION_LABELS: Record<ViolationType, string> = {
  LOCKOUT_ACTIVE: "Trade pendant un verrou actif",
  SESSION_WINDOW: "Hors fenêtre de session",
  SIZE_POLICY: "Taille au-dessus de la politique",
};
