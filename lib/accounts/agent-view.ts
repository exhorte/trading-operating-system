/**
 * I2 (2026-09-26): what the Account screen says about the account MT5 is on
 * and about the execution agent serving it — pure, so every sentence the
 * trader reads is tested. Nothing here decides anything: it describes what
 * the observer and the agent reported (ADR 0001).
 */

import type { AccountSummary, ExecutionAgentStatus } from "@/lib/contracts/snapshots";

export type ViewTone = "profit" | "warning" | "loss" | "info" | "muted";

export interface ViewLine {
  state: string;
  tone: ViewTone;
  detail: string;
}

const TRADE_MODE_LABEL: Record<string, string> = {
  demo: "Démo",
  contest: "Concours",
  real: "RÉEL",
};

/** "Démo" / "RÉEL", server, leverage, hedging or netting — or unknown. */
export function accountKindLine(account: AccountSummary | null): ViewLine {
  if (!account) {
    return { state: "—", tone: "muted", detail: "rien tant que l'observer n'est pas attaché" };
  }
  if (!account.tradeMode) {
    return {
      state: "Inconnu",
      tone: "muted",
      detail: "observer antérieur à I2 : relance-le (scripts/start-live.ps1) pour lire le type de compte",
    };
  }
  const parts: string[] = [];
  if (account.server) {
    parts.push(`serveur ${account.server}`);
  }
  if (account.leverage) {
    parts.push(`levier 1:${account.leverage}`);
  }
  if (account.marginMode && account.marginMode !== "unknown") {
    parts.push(account.marginMode + (account.fifoClose ? " (FIFO)" : ""));
  }
  if (account.tradeAllowed === false) {
    parts.push("trading interdit sur ce compte — mot de passe investisseur : observation seule");
  }
  return {
    state: TRADE_MODE_LABEL[account.tradeMode] ?? "Inconnu",
    tone: account.tradeMode === "real" ? "warning" : "info",
    detail: parts.join(" · "),
  };
}

/** Whether the agent answers for the login the terminal is on. */
export function agentIdentityLine(status: ExecutionAgentStatus | null, account: AccountSummary | null): ViewLine {
  if (!status) {
    return {
      state: "—",
      tone: "muted",
      detail: "aucun agent I1 enregistré pour ce compte (agent absent, refusé, ou antérieur à I1)",
    };
  }
  if (status.identity === "mismatch") {
    return {
      state: "Refus",
      tone: "loss",
      detail: `terminal sur ${status.accountId}, preset attend ${status.expectedAccountId ?? "?"} : l'agent refuse toute commande`,
    };
  }
  if (status.identity === "no_account") {
    return { state: "Refus", tone: "loss", detail: "le terminal n'est connecté à aucun compte" };
  }
  if (account && status.accountId !== account.accountId) {
    return {
      state: "Écart",
      tone: "warning",
      detail: `l'agent sert ${status.accountId}, l'observer voit ${account.accountId}`,
    };
  }
  return { state: status.accountId, tone: "profit", detail: "le login vu par l'agent est celui du terminal" };
}

interface Permission {
  label: string;
  value: boolean | null;
}

function permissions(status: ExecutionAgentStatus): Permission[] {
  return [
    { label: "bouton Algo Trading", value: status.terminalTradeAllowed },
    { label: "case de l'EA", value: status.expertTradeAllowed },
    { label: "experts autorisés (serveur)", value: status.accountTradeExpert },
    { label: "trading autorisé (compte)", value: status.accountTradeAllowed },
  ];
}

/** The four independent permissions an order needs — none settable by
 *  code. In observe mode an OFF is a barrier, not a fault. */
export function permissionsLine(status: ExecutionAgentStatus | null): ViewLine {
  if (!status) {
    return { state: "—", tone: "muted", detail: "publiées par l'agent depuis I1" };
  }
  const list = permissions(status);
  if (list.every((p) => p.value === null)) {
    return { state: "—", tone: "muted", detail: "agent antérieur à I1 : ne les publie pas" };
  }
  const on = list.filter((p) => p.value === true).length;
  return {
    state: `${on}/4`,
    tone: "info",
    detail: list.map((p) => `${p.label} ${p.value === null ? "?" : p.value ? "oui" : "non"}`).join(" · "),
  };
}

/** Other experts attached in the terminal: the Algo Trading button arms
 *  every one of them, not only the Trading OS agent. */
export function foreignExpertsLine(status: ExecutionAgentStatus | null): ViewLine {
  if (!status) {
    return { state: "—", tone: "muted", detail: "listés par l'agent depuis I1" };
  }
  if (status.attachedExperts.length === 0) {
    return { state: "Aucun", tone: "profit", detail: "seul l'agent Trading OS est attaché" };
  }
  return {
    state: String(status.attachedExperts.length),
    tone: "warning",
    detail: `${status.attachedExperts.join(", ")} — Algo Trading les armerait aussi ; l'armement (I4) les refusera`,
  };
}

export function haltLine(status: ExecutionAgentStatus | null): ViewLine {
  if (!status || status.halted === null) {
    return { state: "—", tone: "muted", detail: "kill switch local de l'agent (depuis I1)" };
  }
  return status.halted
    ? { state: "Posé", tone: "warning", detail: "l'agent refuse toute commande ; se lève sur le graphique MT5" }
    : {
        state: "Levé",
        tone: "muted",
        detail: "bouton HALT sur le graphique de l'agent (l'arrêt d'urgence du cockpit le posera avec l'armement, I4)",
      };
}

export function modeLine(status: ExecutionAgentStatus | null): ViewLine {
  if (!status) {
    return { state: "observe", tone: "info", detail: "aucun ordre ne part de ce système" };
  }
  const ceiling = status.modeCeiling ?? "?";
  return {
    state: status.mode,
    tone: "info",
    detail:
      status.mode === "observe" && ceiling === "observe"
        ? "aucun ordre ne part de ce système : cette version de l'agent plafonne à observe"
        : `plafond de cette version : ${ceiling}`,
  };
}
