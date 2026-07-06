"use client";

import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatClockTime } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";

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
      <Card title="Market context">
        <Skeleton className="h-48" />
      </Card>
    );
  }

  const biasTone =
    marketContext.bias === "bullish"
      ? "profit"
      : marketContext.bias === "bearish"
        ? "loss"
        : "muted";

  return (
    <Card
      title={`Market context — ${marketContext.symbol} ${marketContext.timeframe}`}
      untrusted={untrusted}
      actions={<StatusPill tone={biasTone}>{marketContext.bias}</StatusPill>}
    >
      <dl className="flex flex-col gap-2 text-xs">
        <div className="flex justify-between gap-2">
          <dt className="text-muted">Structure</dt>
          <dd className="text-right">{marketContext.structureState}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted">Last event</dt>
          <dd className="text-right">{marketContext.lastStructureEvent}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted">Session</dt>
          <dd>{SESSION_LABELS[marketContext.session] ?? marketContext.session}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted">Liquidity</dt>
          <dd className="text-right">{marketContext.liquidityNote}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted">PD arrays</dt>
          <dd className="text-right">{marketContext.pdArrayNote}</dd>
        </div>
      </dl>

      <div className="mt-3 border-t border-border pt-2">
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-muted">Context score</span>
          <span className="tnum font-semibold">
            {marketContext.score}/{marketContext.maxScore}
          </span>
        </div>
        <ul className="mt-2 flex flex-col gap-1.5">
          {marketContext.scoreBreakdown.map((component) => (
            <li key={component.label} className="flex items-center gap-2 text-[11px]">
              <span className="w-20 shrink-0 text-muted">{component.label}</span>
              <div className="h-1 flex-1 overflow-hidden rounded bg-surface-elevated">
                <div
                  className="h-full rounded bg-info"
                  style={{ width: `${(component.score / component.maxScore) * 100}%` }}
                />
              </div>
              <span className="tnum w-7 text-right text-muted">
                {component.score}/{component.maxScore}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-right text-[10px] text-muted">
          Updated {formatClockTime(marketContext.updatedAt)}
        </p>
      </div>
    </Card>
  );
}
