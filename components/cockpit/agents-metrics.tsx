"use client";

import { Activity, Cpu, FileText, HeartPulse, Radio } from "lucide-react";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatClockTime } from "@/lib/format";
import { HighlightBar, MetricPanel, MetricPanelItem, type MetricTone } from "@/components/ui/metric-panel";
import { StatusPill } from "@/components/ui/status-pill";

const OBSERVER_TONE: Record<string, MetricTone | undefined> = {
  connected: "success",
  degraded: "warning",
  disconnected: "destructive",
};

/**
 * The health of the two links, in the dark panel. The distinction matters
 * here more than anywhere: the observer (read-only) and the EA-05 execution
 * agent are different links, and reading the first as the second is the bug
 * that let the cockpit imply an order could reach MT5 (corrected 2026-09-18).
 */
export function AgentsMetrics() {
  const { agents, executionAgentConnected, executionReports } = useCockpit();
  const untrusted = useIsDataUntrusted();
  const observer = agents[0];

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
          label="Observateur MT5"
          value={observer ? observer.state : "—"}
          tone={observer ? OBSERVER_TONE[observer.state] : undefined}
          hint={observer ? `lecture seule · ${observer.platform} ${observer.version}` : "aucun battement reçu"}
          icon={Radio}
          solidIcon
          untrusted={untrusted}
        />
        <MetricPanelItem
          label="Latence"
          value={observer ? String(observer.latencyMs) : "—"}
          unit={observer ? "ms" : undefined}
          hint="aller-retour de l'observateur"
          icon={Activity}
          untrusted={untrusted}
        />
        <MetricPanelItem
          label="Dernier battement"
          value={observer ? formatClockTime(observer.lastHeartbeatAt) : "—"}
          hint="un battement périmé est signalé « Périmé »"
          icon={HeartPulse}
          untrusted={untrusted}
        />
        <MetricPanelItem
          label="Rapports d'exécution"
          value={String(executionReports.length)}
          hint="reçus depuis le démarrage du cockpit"
          icon={FileText}
          untrusted={untrusted}
        />
      </MetricPanel>
    </>
  );
}
