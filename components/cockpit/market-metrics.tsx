"use client";

import { CalendarClock, ChartCandlestick, Clock, Layers3, Target } from "lucide-react";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { nextRelease } from "@/lib/cockpit/calendar";
import { useMarketContext } from "@/lib/cockpit/use-market-context";
import { useNow } from "@/lib/cockpit/use-now";
import { HighlightBar, MetricPanel, MetricPanelItem } from "@/components/ui/metric-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { SESSION_LABELS } from "./market-context-panel";

const BIAS_LABEL = { bullish: "Haussier", bearish: "Baissier", neutral: "Neutre" } as const;

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * The market context in the dark panel: the bias as the headline, then the
 * score, the session, the structure and the next release. Levels are context,
 * never signals (ADR 0002).
 */
export function MarketMetrics() {
  const { upcomingReleases } = useCockpit();
  const { context: marketContext } = useMarketContext();
  const untrusted = useIsDataUntrusted();
  const nowMs = useNow();

  if (!marketContext) {
    return (
      <>
        <Skeleton className="h-[72px] rounded-xl" />
        <Skeleton className="h-[420px] rounded-xl" />
      </>
    );
  }

  const upcoming = upcomingReleases === null ? null : nextRelease(nowMs, upcomingReleases);
  const biasTone = marketContext.bias === "bullish" ? "profit" : marketContext.bias === "bearish" ? "loss" : "muted";

  return (
    <>
      <HighlightBar
        icon={ChartCandlestick}
        value={BIAS_LABEL[marketContext.bias]}
        label={`${marketContext.symbol} ${marketContext.timeframe}`}
        aside={
          <StatusPill tone={biasTone} onPanel>
            {marketContext.bias}
          </StatusPill>
        }
        className={untrusted ? "opacity-60" : undefined}
      />
      <MetricPanel>
        <MetricPanelItem
          label="Score de contexte"
          value={String(marketContext.score)}
          unit={`/ ${marketContext.maxScore}`}
          progress={(marketContext.score / marketContext.maxScore) * 100}
          hint="somme des composantes du panneau de gauche"
          icon={Target}
          solidIcon
          untrusted={untrusted}
        />
        <MetricPanelItem
          label="Session"
          value={SESSION_LABELS[marketContext.session] ?? marketContext.session}
          hint="fenêtres UTC de tagage du contexte"
          icon={Clock}
          untrusted={untrusted}
        />
        <MetricPanelItem
          label="Structure"
          value={marketContext.structureState}
          hint={`dernier événement : ${marketContext.lastStructureEvent}`}
          icon={Layers3}
          untrusted={untrusted}
        />
        <MetricPanelItem
          label="Prochaine publication"
          value={upcomingReleases === null ? "—" : upcoming ? upcoming.label : "Aucune"}
          tone={upcomingReleases === null ? "destructive" : undefined}
          hint={
            upcomingReleases === null
              ? "calendrier indisponible : la gate news est fermée"
              : upcoming
                ? formatWhen(upcoming.scheduledAt)
                : "rien de prévu au calendrier"
          }
          icon={CalendarClock}
        />
      </MetricPanel>
    </>
  );
}
