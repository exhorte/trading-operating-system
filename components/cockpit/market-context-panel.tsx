"use client";

import { ChartCandlestick } from "lucide-react";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { useMarketContext } from "@/lib/cockpit/use-market-context";
import { formatClockTime } from "@/lib/format";
import { Panel } from "@/components/ui/panel";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";

export const SESSION_LABELS: Record<string, string> = {
  asia: "Asia",
  london: "London",
  new_york_am: "New York AM",
  new_york_pm: "New York PM",
  off_session: "Off session",
};

export function MarketContextPanel() {
  const { account } = useCockpit();
  const { context: marketContext, error } = useMarketContext();
  const untrusted = useIsDataUntrusted();

  if (!marketContext) {
    return (
      <Panel title="Market context" icon={ChartCandlestick}>
        {account === null ? (
          <p className="text-sm text-muted-foreground">
            Aucun compte rattaché : le contexte se calcule sur les bougies du compte.
          </p>
        ) : error ? (
          <p className="text-sm text-destructive">{error.message}</p>
        ) : (
          <Skeleton className="h-48" />
        )}
      </Panel>
    );
  }

  const biasTone =
    marketContext.bias === "bullish" ? "profit" : marketContext.bias === "bearish" ? "loss" : "muted";

  return (
    <Panel
      title={`Market context — ${marketContext.symbol} ${marketContext.timeframe}`}
      description={`mis à jour à ${formatClockTime(marketContext.updatedAt)}`}
      icon={ChartCandlestick}
      untrusted={untrusted}
      actions={<StatusPill tone={biasTone}>{marketContext.bias}</StatusPill>}
    >
      <dl className="flex flex-col divide-y text-sm">
        <div className="flex justify-between gap-3 py-2 first:pt-0">
          <dt className="text-muted-foreground">Structure</dt>
          <dd className="text-right">{marketContext.structureState}</dd>
        </div>
        <div className="flex justify-between gap-3 py-2">
          <dt className="text-muted-foreground">Last event</dt>
          <dd className="text-right">{marketContext.lastStructureEvent}</dd>
        </div>
        <div className="flex justify-between gap-3 py-2">
          <dt className="text-muted-foreground">Session</dt>
          <dd>{SESSION_LABELS[marketContext.session] ?? marketContext.session}</dd>
        </div>
        <div className="flex justify-between gap-3 py-2">
          <dt className="text-muted-foreground">Liquidity</dt>
          <dd className="text-right">{marketContext.liquidityNote}</dd>
        </div>
        <div className="flex justify-between gap-3 py-2 last:pb-0">
          <dt className="text-muted-foreground">PD arrays</dt>
          <dd className="text-right">{marketContext.pdArrayNote}</dd>
        </div>
      </dl>

      <div className="mt-4 border-t pt-4">
        <div className="flex items-baseline justify-between text-sm">
          <span className="text-muted-foreground">Context score</span>
          <span className="tnum font-semibold">
            {marketContext.score}/{marketContext.maxScore}
          </span>
        </div>
        <ul className="mt-3 flex flex-col gap-2">
          {marketContext.scoreBreakdown.map((component) => (
            <li key={component.label} className="flex items-center gap-3 text-sm">
              <span className="w-24 shrink-0 text-muted-foreground">{component.label}</span>
              <Progress value={(component.score / component.maxScore) * 100} className="h-1.5 flex-1" />
              <span className="tnum w-9 text-right text-muted-foreground">
                {component.score}/{component.maxScore}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}
