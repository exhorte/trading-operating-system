"use client";

import { useEffect, useState } from "react";
import { useCockpit } from "@/lib/realtime/provider";
import type { ActiveProfile } from "@/lib/accounts/active-profile";
import { formatAge } from "@/lib/format";
import type { ConnectionState } from "@/lib/contracts/enums";
import { Card } from "@/components/ui/card";
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
  const { connection, environment, account, agents, executionAgentConnected } = useCockpit();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 5_000);
    return () => clearInterval(timer);
  }, []);

  const observer = agents[0] ?? null;
  const hub = HUB_STATES[connection];

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
        ? "TCP 9765 — requis par la gate de connexion du pré-vol"
        : "facultatif pour observer ; la gate de connexion du pré-vol le requiert",
    },
    {
      label: "Mode d'exécution",
      tone: "info",
      state: "observe",
      detail: "aucun ordre ne part de ce système (EA-07 fermé)",
    },
  ];

  return (
    <Card title="Liaison MT5">
      <ul className="flex flex-col">
        {links.map((link) => (
          <li
            key={link.label}
            className="grid grid-cols-[minmax(0,11rem)_auto_minmax(0,1fr)] items-center gap-3 border-t border-border py-1.5 text-xs first:border-t-0 first:pt-0"
          >
            <span className="text-muted">{link.label}</span>
            <StatusPill tone={link.tone}>{link.state}</StatusPill>
            <span className="truncate text-[11px] text-muted" title={link.detail}>
              {link.detail}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
