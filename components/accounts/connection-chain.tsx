"use client";

import { useEffect, useState } from "react";
import { Cable } from "lucide-react";
import { coreBaseUrl } from "@/lib/api/client";
import type { AccountStatus } from "@/lib/api/generated";
import { useCockpit } from "@/lib/realtime/provider";
import type { ConnectionState } from "@/lib/realtime/store";
import type { AccountProfile } from "@/lib/accounts/profile";
import { PROVIDER_NAMES } from "@/lib/accounts/profile";
import {
  accountKindLine,
  agentIdentityLine,
  foreignExpertsLine,
  haltLine,
  modeLine,
  permissionsLine,
  type ViewLine,
} from "@/lib/accounts/agent-view";
import { formatAge } from "@/lib/format";
import { Panel } from "@/components/ui/panel";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

interface Link {
  label: string;
  tone: PillTone;
  state: string;
  detail: string;
}

const UNREACHABLE = "le cœur ne répond pas — python -m trading_os serve, ou scripts/start.ps1";

const TERMINAL_STATES: Record<AccountStatus, { tone: PillTone; state: string }> = {
  CONNECTED: { tone: "profit", state: "Attaché" },
  CONNECTING: { tone: "warning", state: "Connexion…" },
  ERROR: { tone: "loss", state: "En erreur" },
  DISCONNECTED: { tone: "muted", state: "Détaché" },
};

/**
 * Account — « qu'est-ce qui est branché, maillon par maillon ». Each link of
 * the chain from the cockpit to the MT5 terminal, as the store knows it, so
 * "not connected" always says *which* link is missing. Nothing here opens a
 * connection: the terminal is logged in by the trader, the core attaches to it
 * (ADR 0003, 0013).
 */
export function ConnectionChain({ profile }: { profile: AccountProfile | null }) {
  const {
    connection,
    connectionIssue,
    registered,
    account,
    health,
    agent,
    executionAgentConnected,
  } = useCockpit();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 5_000);
    return () => clearInterval(timer);
  }, []);

  const base = coreBaseUrl();
  const coreStates: Record<ConnectionState, { tone: PillTone; state: string; detail: string }> = {
    connecting: { tone: "muted", state: "Connexion…", detail: `WebSocket → cœur Python (${base})` },
    connected: { tone: "profit", state: "Connecté", detail: `WebSocket → cœur Python (${base})` },
    reconnecting: { tone: "warning", state: "Reconnexion…", detail: connectionIssue ?? UNREACHABLE },
    // The watchdog's verdict, not the socket's: the stream is joined, but the core has stopped beating.
    stale: {
      tone: "warning",
      state: "Périmé",
      detail: "flux joint, mais plus aucun battement du cœur : les chiffres ne sont plus frais",
    },
    degraded: {
      tone: "warning",
      state: "Dégradé",
      detail:
        health?.findings
          .filter((f) => f.severity === "high" || f.severity === "critical")
          .map((f) => f.detail)
          .join(" · ") || "le cœur signale un défaut",
    },
    disconnected: { tone: "loss", state: "Déconnecté", detail: connectionIssue ?? UNREACHABLE },
  };
  const core = coreStates[connection];
  const line = (label: string, view: ViewLine): Link => ({ label, ...view });
  const terminal = registered ? TERMINAL_STATES[registered.status] : null;

  const links: Link[] = [
    { label: "Cœur (flux temps réel)", tone: core.tone, state: core.state, detail: core.detail },
    {
      label: "Terminal MT5 (lecture seule)",
      tone: terminal?.tone ?? "muted",
      state: terminal?.state ?? "Aucun",
      detail: !registered
        ? "aucun compte actif — enregistre-en un dans Settings, puis rattache-le"
        : registered.status === "CONNECTED"
          ? `${account ? `dernière lecture il y a ${formatAge(account.observedAt, now)} · ` : ""}${registered.server}`
          : (registered.statusDetail ?? "ce compte n'est pas rattaché — bouton « Rattacher » plus bas"),
    },
    {
      label: "Compte transmis par MT5",
      tone: account ? "profit" : "muted",
      state: registered && account ? String(registered.login) : "Aucun",
      detail: account ? `broker « ${account.broker} » · ${account.currency}` : "rien tant que le terminal n'est pas attaché",
    },
    line("Type de compte", accountKindLine(account)),
    {
      label: "Profil du compte",
      tone: profile ? "profit" : registered ? "warning" : "muted",
      state: registered ? PROVIDER_NAMES[registered.provider] : "—",
      detail: profile ? profile.label : registered ? "règles en cours de lecture…" : "—",
    },
    {
      label: "Agent d'exécution EA-05",
      tone: executionAgentConnected ? "profit" : "muted",
      state: executionAgentConnected ? "Connecté" : "Non connecté",
      detail: executionAgentConnected
        ? `TCP · ${agent?.agentId ?? "?"} ${agent?.buildId ?? agent?.agentVersion ?? ""} — requis par la gate de connexion du pré-vol`
        : "facultatif pour observer ; la gate de connexion du pré-vol le requiert",
    },
    line("Login vu par l'agent", agentIdentityLine(agent, registered?.login ?? null)),
    line("Permissions de trading", permissionsLine(agent)),
    line("Autres EA attachés", foreignExpertsLine(agent)),
    line("Halt local", haltLine(agent)),
    line("Mode d'exécution", modeLine(agent)),
  ];

  return (
    <Panel title="Liaison MT5" description="chaque maillon, du cockpit au terminal" icon={Cable}>
      <ul className="flex flex-col">
        {links.map((link) => (
          <li
            key={link.label}
            className="grid grid-cols-1 gap-1 border-t py-2.5 text-sm first:border-t-0 first:pt-0 last:pb-0 sm:grid-cols-[minmax(0,11rem)_auto_minmax(0,1fr)] sm:items-center sm:gap-3"
          >
            <span className="text-muted-foreground">{link.label}</span>
            <StatusPill tone={link.tone}>{link.state}</StatusPill>
            <span className="text-xs leading-snug text-muted-foreground">{link.detail}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
