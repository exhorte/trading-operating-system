"use client";

import { Activity, Cpu, FileText, HeartPulse, Radio } from "lucide-react";
import type { AccountStatus } from "@/lib/api/generated";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatClockTime } from "@/lib/format";
import { HighlightBar, MetricPanel, MetricPanelItem, type MetricTone } from "@/components/ui/metric-panel";
import { StatusPill } from "@/components/ui/status-pill";

const TERMINAL_TONE: Record<AccountStatus, MetricTone | undefined> = {
  CONNECTED: "success",
  CONNECTING: "warning",
  ERROR: "destructive",
  DISCONNECTED: undefined,
};

const TERMINAL_LABEL: Record<AccountStatus, string> = {
  CONNECTED: "attaché",
  CONNECTING: "connexion…",
  ERROR: "en erreur",
  DISCONNECTED: "détaché",
};

/**
 * The health of the two links, in the dark panel. The distinction matters
 * here more than anywhere: the terminal read (read-only) and the EA-05
 * execution agent are different links, and reading the first as the second is
 * the bug that let the cockpit imply an order could reach MT5 (corrected
 * 2026-09-18).
 */
export function AgentsMetrics() {
  const { registered, executionAgentConnected, agent, agentPulse, commands } = useCockpit();
  const untrusted = useIsDataUntrusted();

  return (
    <>
      <HighlightBar
        icon={Cpu}
        value={executionAgentConnected ? "Connecté" : "Aucun agent"}
        label="Agent d'exécution (EA-05)"
        aside={
          <StatusPill tone={executionAgentConnected ? "profit" : "loss"} onPanel>
            {executionAgentConnected ? "connected" : "no agent"}
          </StatusPill>
        }
      />
      <MetricPanel>
        <MetricPanelItem
          label="Terminal MT5"
          value={registered ? TERMINAL_LABEL[registered.status] : "—"}
          tone={registered ? TERMINAL_TONE[registered.status] : undefined}
          hint={registered ? `lecture seule · ${registered.server}` : "aucun compte actif"}
          icon={Radio}
          solidIcon
          untrusted={untrusted}
        />
        <MetricPanelItem
          label="Latence de l'agent"
          value={agentPulse ? String(Math.round(agentPulse.latencyMs)) : "—"}
          unit={agentPulse ? "ms" : undefined}
          hint={agent ? "aller-retour de l'agent d'exécution" : "aucun agent connecté"}
          icon={Activity}
          untrusted={untrusted}
        />
        <MetricPanelItem
          label="Dernier battement"
          value={agentPulse ? formatClockTime(agentPulse.receivedAt) : "—"}
          hint="un lien muet est signalé « Périmé »"
          icon={HeartPulse}
          untrusted={untrusted}
        />
        <MetricPanelItem
          label="Commandes d'exécution"
          value={String(commands.length)}
          hint="les plus récentes, avec l'état que le cœur leur donne"
          icon={FileText}
          untrusted={untrusted}
        />
      </MetricPanel>
    </>
  );
}
