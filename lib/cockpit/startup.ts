/**
 * « Démarrer le système » (ADR 0034) — the words and tones of the thirteen stages, the conditions before a position and the
 * modes of the plan. Pure functions, tested; the screen only lays them out.
 *
 * Three things stay apart in every sentence: starting the application, starting the trading system, authorising automatic
 * trading. The first authorises no order; the second never climbs past CONFIRM; the third is a gesture of its own.
 */

import type { AutonomyMode, PlanMode, StartupStageState, StartupStatus } from "@/lib/api/generated";
import type { Tone } from "./close-all";

export const START_LABEL = "DÉMARRER LE SYSTÈME";
export const REAL_ACCOUNT_BANNER = "COMPTE RÉEL — LES ORDRES PEUVENT ENTRAÎNER UNE PERTE FINANCIÈRE";

export const STATE_LABELS: Record<StartupStageState, string> = {
  STOPPED: "Arrêté",
  STARTING: "Démarrage…",
  READY: "Prêt",
  RUNNING: "En marche",
  DEGRADED: "Dégradé",
  FAILED: "En échec",
  HALTED: "HALTED",
};

export function stateTone(state: StartupStageState): Tone {
  switch (state) {
    case "RUNNING":
    case "READY":
      return "profit";
    case "STARTING":
      return "info";
    case "DEGRADED":
      return "warning";
    case "FAILED":
    case "HALTED":
      return "loss";
    default:
      return "muted";
  }
}

export const MODE_LABELS: Record<PlanMode, string> = {
  OFF: "OFF — arrêté",
  OBSERVE: "OBSERVE — analyse seule",
  PAPER: "PAPER — ordres simulés",
  CONFIRM: "CONFIRM — confirmation humaine (démo)",
  DEMO_AUTO: "DEMO_AUTO — automatique sur démo",
  LIVE_CONFIRM: "LIVE_CONFIRM — confirmation humaine (réel)",
  LIVE_AUTO: "LIVE_AUTO — automatique sur réel",
  HALTED: "HALTED — entrées coupées",
};

export function modeTone(mode: PlanMode): Tone {
  switch (mode) {
    case "LIVE_AUTO":
    case "LIVE_CONFIRM":
    case "HALTED":
      return "loss";
    case "DEMO_AUTO":
    case "CONFIRM":
      return "warning";
    case "OBSERVE":
    case "PAPER":
      return "info";
    default:
      return "muted";
  }
}

/** What each mode lets happen, in one line — shown under the current mode. */
export const MODE_RIGHTS: Record<PlanMode, string> = {
  OFF: "Rien ne tourne côté stratégie. Aucun ordre.",
  OBSERVE: "Le système analyse le marché et journalise les setups. Aucun ordre n'est envoyé.",
  PAPER: "Les ordres sont simulés dans le cœur. Aucun ordre n'atteint le courtier.",
  CONFIRM: "Chaque ordre attend votre confirmation, puis part vers l'agent (compte démo).",
  DEMO_AUTO: "Le système peut prendre des positions seul sur le compte démo, tant que tout est vert.",
  LIVE_CONFIRM: "Chaque ordre réel attend votre confirmation. Argent réel.",
  LIVE_AUTO: "Le système peut prendre des positions réelles seul, tant que tout est vert. Argent réel.",
  HALTED: "Aucune nouvelle entrée. Les positions ouvertes restent surveillées ; fermer reste possible à la main.",
};

/** The checks of § 2.2 by their id: the trader's words (the core's `label` is English). */
export const CHECK_LABELS: Record<string, string> = {
  python_core: "Cœur Python sain",
  database: "Base de données disponible",
  mt5_connected: "Connexion MT5 active",
  correct_account: "Compte identifié (le terminal est sur le bon compte)",
  symbols_available: "Symboles correctement résolus",
  risk_engine: "Risk Engine opérationnel",
  sizing_valid: "Calcul des lots valide",
  reconciliation: "Réconciliation terminée",
  kill_switch_available: "Kill switch disponible (agent)",
  heartbeat: "Agent MQL5 connecté, heartbeat valide",
  supervisor: "Superviseur sain",
  execution_engine: "Moteur d'exécution sain",
  strategy_valid: "Stratégie valide",
  position_management: "Gestion des sorties valide",
  no_critical_incident: "Aucun incident critique ouvert",
  account_limits_configured: "Limites de compte écrites par vous",
  market_data_fresh: "Données de marché fraîches",
  guardian_running: "Account Guardian opérationnel",
  no_unknown_commands: "Aucune commande UNKNOWN non résolue",
  risk_limits_loaded: "Limites jour/semaine et capital initial chargés",
  no_safety_block: "Aucun verrou ni blocage de sécurité",
  mode_authorized: "Mode d'autonomie explicitement autorisé (plafond du compte)",
  account: "Compte identifié",
  ceiling: "Plafond du compte",
  halted: "Système non arrêté",
};

export function checkLabel(id: string, fallback: string): string {
  return CHECK_LABELS[id] ?? fallback;
}

/** The sentence under the verdict. */
export function verdictLine(status: StartupStatus): string {
  if (status.halted) {
    return "Système arrêté (HALTED) : aucune nouvelle entrée. Acquittez l'arrêt pour pouvoir redémarrer.";
  }
  if (status.entriesAuthorized) {
    return `Le système peut prendre des positions (${status.planMode}) : toutes les conditions sont réunies.`;
  }
  if (!status.rights.sendsOrders) {
    return status.planMode === "OFF"
      ? "Le système est arrêté : aucune position ne sera prise."
      : "Mode sans ordre réel : le système analyse, il ne prend pas de position.";
  }
  const missing = status.blockers.length;
  return `Aucune position ne sera prise : ${missing} condition${missing > 1 ? "s" : ""} non remplie${missing > 1 ? "s" : ""}.`;
}

/** What the « stop » buttons mean — three distinct gestures, never merged with closing everything. */
export const STOP_ENTRIES: { target: AutonomyMode; label: string; hint: string }[] = [
  { target: "OBSERVE", label: "Arrêter les nouvelles entrées", hint: "Passe en OBSERVE : plus aucun ordre, l'analyse continue." },
  { target: "OFF", label: "Arrêter les moteurs de stratégie", hint: "Passe en OFF : les stratégies n'évaluent plus. Le Guardian continue de surveiller." },
];

export function runLine(status: StartupStatus): string | null {
  const run = status.run;
  if (!run) {
    return null;
  }
  switch (run.state) {
    case "RUNNING":
      return "Démarrage en cours…";
    case "DONE":
      return run.message;
    case "PARTIAL":
      return `Démarré avec réserve : ${run.message}`;
    case "BLOCKED":
      return `Démarrage bloqué : ${run.message}`;
  }
}
