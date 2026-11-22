/**
 * System Center (ADR 0039 § 8) — the words and tones of what the core says of the MetaTrader terminals and their agents.
 * Pure functions, tested; the screen only lays them out. **Everything shown comes from the core** (`GET /api/system/center`):
 * no status is invented here, a value the core did not give is shown as unknown — never as green.
 *
 * Two lines stay apart on every card: whether the agent is *technically ready*, and whether an order could be placed
 * (« Execution Authorization »). A terminal can be READY with the authorization BLOCKED — SYSTEM MODE = OFF.
 */

import type { ConditionView, Mt5TerminalView, SystemCenterView } from "@/lib/api/generated";
import type { Tone } from "./close-all";

export const VERDICT_LABELS: Record<string, string> = {
  READY: "Prêt (technique)",
  VALIDATING: "En validation",
  BLOCKED: "Bloqué",
};

export function verdictTone(verdict: string): Tone {
  switch (verdict) {
    case "READY":
      return "profit";
    case "VALIDATING":
      return "warning";
    case "BLOCKED":
      return "loss";
    default:
      return "muted";
  }
}

export const LIGHT_LABELS: Record<string, string> = {
  GREEN: "OK",
  RED: "Rouge",
  PENDING: "En attente",
};

export function lightTone(light: string): Tone {
  return light === "GREEN" ? "profit" : light === "RED" ? "loss" : light === "PENDING" ? "warning" : "muted";
}

/** The deployment states the launcher journals (ADR 0039 § 3) — a memory of the last thing seen, never a proof. */
export const STATE_LABELS: Record<string, string> = {
  NOT_INSTALLED: "Non installé",
  DEPLOYING: "Déploiement…",
  DEPLOYED: "Déployé",
  TERMINAL_STOPPING: "Fermeture du terminal…",
  TERMINAL_STARTING: "Lancement du terminal…",
  EA_LOADING: "Chargement de l'agent…",
  EA_CONNECTED: "Agent connecté",
  EA_VALIDATING: "Validation…",
  EA_READY: "Agent prêt",
  EA_BLOCKED: "Agent bloqué",
  EA_DISCONNECTED: "Agent déconnecté",
  EA_ERROR: "Erreur",
};

export function stateLabel(state: string | null | undefined): string {
  return state ? (STATE_LABELS[state] ?? state) : "Aucun état journalisé";
}

/** What the screen says it is: a reading. It never offers to arm, confirm or start anything. */
export const READ_ONLY_NOTE =
  "Lecture seule : cet écran montre ce que le cœur et le lanceur ont observé. Il ne ferme rien, ne déploie rien, ne lance rien et ne relève aucun mode.";

/** The commands of the actions that change a file or a process. They are shown to be copied, never run from here (ADR 0039 § 8). */
export function commandsFor(terminal: Mt5TerminalView): { label: string; command: string }[] {
  const id = terminal.terminal.terminalId;
  const commands = [
    { label: "Compiler l'agent", command: `launcher mt5 build --terminal ${id}` },
    { label: "Déployer l'agent", command: `launcher mt5 deploy --terminal ${id}` },
    { label: "Préparer le preset", command: `launcher mt5 prepare --terminal ${id}` },
    { label: "Lancer MetaTrader 5 (simulation d'abord)", command: `launcher mt5 start --terminal ${id} --dry-run` },
    { label: "Lire l'état", command: `launcher mt5 status --terminal ${id}` },
  ];
  return commands;
}

export const COMMAND_PREFIX = "TradingOS.bat MT5 — ou, depuis python\\ : python -m trading_os ";

/** Age of a heartbeat in words — « inconnu » when the core did not say. */
export function heartbeatLine(ageSeconds: number | null | undefined): string {
  if (ageSeconds === null || ageSeconds === undefined) {
    return "inconnu";
  }
  return ageSeconds < 1 ? "à l'instant" : `il y a ${Math.round(ageSeconds)} s`;
}

export function authorizationLine(terminal: Mt5TerminalView): string {
  const authorization = terminal.readiness.executionAuthorization;
  return authorization.allowed
    ? "AUTORISÉE"
    : `BLOQUÉE${authorization.reasons.length ? ` — ${authorization.reasons.join(", ")}` : ""}`;
}

/** Conditions that are not green, red first — what a person wants to read first. */
export function openConditions(terminal: Mt5TerminalView): ConditionView[] {
  const rank = (condition: ConditionView) => (condition.light === "RED" ? 0 : condition.light === "PENDING" ? 1 : 2);
  return terminal.readiness.conditions.filter((condition) => condition.light !== "GREEN").sort((a, b) => rank(a) - rank(b));
}

/** The one sentence at the top: how many terminals, how many ready — and that none of them being ready authorises nothing. */
export function summaryLine(center: SystemCenterView): string {
  const total = center.terminals.length;
  if (total === 0) {
    return "Aucun terminal enregistré : « launcher mt5 plan » dit comment en enregistrer un.";
  }
  const ready = center.terminals.filter((item) => item.readiness.verdict === "READY").length;
  const blocked = center.terminals.filter((item) => item.readiness.verdict === "BLOCKED").length;
  return `${total} terminal(aux) enregistré(s) : ${ready} prêt(s) techniquement, ${blocked} bloqué(s). Mode du système : ${center.executionMode}.`;
}
