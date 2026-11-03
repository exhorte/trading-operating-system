"use client";

import { CircleHelp } from "lucide-react";
import { useApi } from "@/lib/api/use-api";
import { describeOpportunity, groupReasons, headlineTone, SOURCE_LABEL } from "@/lib/cockpit/why";
import { useIsDataUntrusted } from "@/lib/realtime/provider";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";

const REFRESH_ON = [
  "autonomy.mode_changed",
  "autonomy.readiness_changed",
  "autonomy.halted",
  "risk.state_updated",
  "strategy.evaluation_completed",
] as const;

/**
 * « Pourquoi pas de trade ? » (ADR 0028) — one sentence, then the reasons the core already states, blocking ones first. It reads the core's
 * answer and adds no rule and no button: a reason is not something to get around, it is something to read (the process is the product).
 */
export function WhyNoTradePanel() {
  const { data, error } = useApi("autonomy_why_no_trade", {}, { refreshOn: REFRESH_ON, pollMs: 15_000 });
  const untrusted = useIsDataUntrusted();

  if (!data) {
    return (
      <Panel title="Pourquoi pas de trade ?" icon={CircleHelp}>
        {error ? <p className="text-sm text-destructive">{error.message}</p> : <Skeleton className="h-24" />}
      </Panel>
    );
  }

  const { blocking, informing } = groupReasons(data.reasons);
  return (
    <Panel
      title="Pourquoi pas de trade ?"
      description={`mode ${data.mode} · plafond ${data.ceiling}`}
      icon={CircleHelp}
      untrusted={untrusted}
      actions={
        <StatusPill tone={headlineTone(data)}>{data.realOrdersPossible ? "rien ne bloque" : "aucun ordre réel"}</StatusPill>
      }
    >
      <p className="text-sm leading-snug font-medium text-foreground [overflow-wrap:anywhere]">{data.headline}</p>

      {data.opportunities.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1.5 text-sm" aria-label="Opportunités récentes">
          {data.opportunities.map((opportunity) => (
            <li key={`${opportunity.strategyId}-${opportunity.symbol}-${opportunity.at}`} className="flex items-start gap-2">
              <StatusPill tone="accent">proposé</StatusPill>
              <span className="min-w-0 [overflow-wrap:anywhere]">{describeOpportunity(opportunity)}</span>
            </li>
          ))}
        </ul>
      )}

      {blocking.length + informing.length > 0 && (
        <ul className="mt-4 flex flex-col gap-2 border-t pt-4 text-sm" aria-label="Raisons">
          {[...blocking, ...informing].map((reason) => (
            <li key={`${reason.source}-${reason.code}`} className="flex items-start gap-2">
              <StatusPill tone={reason.blocking ? "warning" : "muted"}>{SOURCE_LABEL[reason.source]}</StatusPill>
              <span className="min-w-0 text-muted-foreground [overflow-wrap:anywhere]">{reason.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
