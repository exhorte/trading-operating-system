"use client";

import { useEffect, useState } from "react";
import { Cable } from "lucide-react";
import { useCockpit } from "@/lib/realtime/provider";
import type { ActiveProfile } from "@/lib/accounts/active-profile";
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
import type { ConnectionState } from "@/lib/contracts/enums";
import { Panel } from "@/components/ui/panel";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

interface Link {
  label: string;
  tone: PillTone;
  state: string;
  detail: string;
}

const UNREACHABLE = "le backend ne répond pas (docker, port 5080) — voir le runbook, section 2";

const HUB_STATES: Record<ConnectionState, { tone: PillTone; state: string; detail: string }> = {
  mock: { tone: "info", state: "Simulé", detail: "source mock" },
  connecting: { tone: "muted", state: "Connexion…", detail: "SignalR → passerelle .NET (docker, port 5080)" },
  connected: { tone: "profit", state: "Connecté", detail: "SignalR → passerelle .NET (docker, port 5080)" },
  reconnecting: { tone: "warning", state: "Reconnexion…", detail: UNREACHABLE },
  // The watchdog's verdict, not the socket's: the hub is joined, but no MT5
  // heartbeat has arrived for a while — usually no observer at all.
  stale: {
    tone: "warning",
    state: "Périmé",
    detail: "hub joint, mais aucun battement de cœur MT5 récent : les chiffres ne sont plus frais",
  },
  degraded: { tone: "warning", state: "Dégradé", detail: "flux partiel" },
  disconnected: { tone: "loss", state: "Déconnecté", detail: UNREACHABLE },
  error: { tone: "loss", state: "Erreur", detail: UNREACHABLE },
};

/**
 * Account — « qu'est-ce qui est branché, maillon par maillon ». Each link of
 * the chain from the cockpit to the MT5 terminal, as the store knows it, so
 * "not connected" always says *which* link is missing. Nothing here opens a
 * connection: the terminal is logged in by the trader, the observer attaches
 * to it (ADR 0003).
 */
export function ConnectionChain({ profile }: { profile: ActiveProfile | null }) {
  const { connection, environment, account, agents, executionAgentConnected, executionAgentStatus } = useCockpit();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 5_000);
    return () => clearInterval(timer);
  }, []);

  const observer = agents[0] ?? null;
  const hub = HUB_STATES[connection];
  // I2: what the observer and the agent reported about the account and
  // about the agent itself (lib/accounts/agent-view.ts, tested).
  const line = (label: string, view: ViewLine): Link => ({ label, ...view });

  const links: Link[] = [
    {
      label: "Backend (hub temps réel)",
      tone: hub.tone,
      state: hub.state,
      detail:
        environment === "mock"
          ? "Source mock : flux scripté, aucun terminal réel derrière"
          : hub.detail,
    },
    {
      label: "Observer MT5 (lecture seule)",
      tone: observer ? (observer.state === "connected" ? "profit" : "loss") : "muted",
      state: observer ? (observer.state === "connected" ? "Attaché" : "Détaché") : "Absent",
      detail: observer
        ? `dernier signe de vie il y a ${formatAge(observer.lastHeartbeatAt, now)} · ${observer.version}`
        : "aucun hello reçu depuis le démarrage du backend — l'observer tourne-t-il ?",
    },
    {
      label: "Compte transmis par MT5",
      tone: account ? "profit" : "muted",
      state: account ? account.accountId : "Aucun",
      detail: account ? `broker « ${account.broker} » · ${account.currency}` : "rien tant que l'observer n'est pas attaché",
    },
    line("Type de compte", accountKindLine(account)),
    {
      label: "Profil reconnu",
      tone: profile ? "profit" : account ? "warning" : "muted",
      state: profile ? (profile.firm === "ftmo" ? "FTMO" : "Exness") : account ? "Non reconnu" : "—",
      detail: profile
        ? profile.label
        : account
          ? "règles par défaut — voir le texte de reconnaissance dans Settings"
          : "—",
    },
    {
      label: "Agent d'exécution EA-05",
      tone: executionAgentConnected ? "profit" : "muted",
      state: executionAgentConnected ? "Connecté" : "Non connecté",
      detail: executionAgentConnected
        ? `TCP 9765${executionAgentStatus ? ` · ${executionAgentStatus.agentId} ${executionAgentStatus.buildId ?? executionAgentStatus.agentVersion}` : ""} — requis par la gate de connexion du pré-vol`
        : "facultatif pour observer ; la gate de connexion du pré-vol le requiert",
    },
    line("Login vu par l'agent", agentIdentityLine(executionAgentStatus, account)),
    line("Permissions de trading", permissionsLine(executionAgentStatus)),
    line("Autres EA attachés", foreignExpertsLine(executionAgentStatus)),
    line("Halt local", haltLine(executionAgentStatus)),
    line("Mode d'exécution", modeLine(executionAgentStatus)),
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
