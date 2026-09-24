"use client";

import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatClockTime } from "@/lib/format";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { Progress } from "@/components/ui/progress";

const SESSION_LABELS: Record<string, string> = {
  asia: "Asia",
  london: "London",
  new_york_am: "New York AM",
  new_york_pm: "New York PM",
  off_session: "Off session",
};

export function MarketContextPanel() {
  const { marketContext } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (!marketContext) {
    return (
      <Panel title="Market context">
        <Skeleton className="h-48" />
      </Panel>
    );
  }

  const biasTone =
    marketContext.bias === "bullish"
      ? "profit"
      : marketContext.bias === "bearish"
        ? "loss"
        : "muted";

  return (
    <Panel
      title={`Market context — ${marketContext.symbol} ${marketContext.timeframe}`}
      untrusted={untrusted}
      actions={<StatusPill tone={biasTone}>{marketContext.bias}</StatusPill>}
    >
      <dl className="flex flex-col gap-2 text-xs">
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Structure</dt>
          <dd className="text-right">{marketContext.structureState}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Last event</dt>
          <dd className="text-right">{marketContext.lastStructureEvent}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Session</dt>
          <dd>{SESSION_LABELS[marketContext.session] ?? marketContext.session}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Liquidity</dt>
          <dd className="text-right">{marketContext.liquidityNote}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">PD arrays</dt>
          <dd className="text-right">{marketContext.pdArrayNote}</dd>
        </div>
      </dl>

      <div className="mt-3 border-t border-border pt-2">
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-muted-foreground">Context score</span>
          <span className="tnum font-semibold">
            {marketContext.score}/{marketContext.maxScore}
          </span>
        </div>
        <ul className="mt-2 flex flex-col gap-1.5">
          {marketContext.scoreBreakdown.map((component) => (
            <li key={component.label} className="flex items-center gap-2 text-xs">
              <span className="w-20 shrink-0 text-muted-foreground">{component.label}</span>
              <Progress
                value={(component.score / component.maxScore) * 100}
                className="h-1.5 flex-1 bg-primary/12"
                indicatorClassName="bg-primary"
              />
              <span className="tnum w-7 text-right text-muted-foreground">
                {component.score}/{component.maxScore}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-right text-[11px] text-muted-foreground">
          Updated {formatClockTime(marketContext.updatedAt)}
        </p>
      </div>
    </Panel>
  );
}
