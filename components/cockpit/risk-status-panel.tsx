"use client";

import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatPercent } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";

function LimitBar({
  label,
  used,
  limit,
}: {
  label: string;
  used: number;
  limit: number;
}) {
  const ratio = Math.min(1, used / limit);
  const barColor = ratio > 0.8 ? "bg-loss" : ratio > 0.5 ? "bg-warning" : "bg-profit";
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-muted">{label}</span>
        <span className="tnum">
          {formatPercent(used)} / {formatPercent(limit)}
        </span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded bg-surface-elevated">
        <div className={`h-full rounded ${barColor}`} style={{ width: `${ratio * 100}%` }} />
      </div>
    </div>
  );
}

export function RiskStatusPanel() {
  const { risk } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (!risk) {
    return (
      <Card title="Risk status">
        <Skeleton className="h-40" />
      </Card>
    );
  }

  const tone = risk.state === "normal" ? "profit" : risk.state === "warning" ? "warning" : "loss";

  return (
    <Card
      title="Risk status"
      untrusted={untrusted}
      actions={<StatusPill tone={tone}>{risk.state}</StatusPill>}
    >
      <div className="flex flex-col gap-3">
        <LimitBar
          label="Daily loss"
          used={risk.dailyLossUsedPercent}
          limit={risk.dailyLossLimitPercent}
        />
        <LimitBar
          label="Max drawdown"
          used={risk.maxDrawdownUsedPercent}
          limit={risk.maxDrawdownLimitPercent}
        />
        <div className="flex justify-between text-xs text-muted">
          <span>
            Trades today:{" "}
            <span className="tnum text-foreground">
              {risk.tradesToday}/{risk.maxTradesPerDay}
            </span>
          </span>
          <span>
            Consecutive losses:{" "}
            <span className="tnum text-foreground">{risk.consecutiveLosses}</span>
          </span>
        </div>
        {risk.lockoutReason && (
          <p className="rounded border border-loss/40 bg-loss/10 px-2 py-1 text-xs text-loss">
            Lockout: {risk.lockoutReason}
          </p>
        )}
        <ul className="flex flex-col gap-1">
          {risk.gates.map((gate) => (
            <li key={gate.gateId} className="flex items-center justify-between gap-2 text-xs">
              <span className="flex items-center gap-1.5">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    gate.state === "open" ? "bg-profit" : "bg-warning"
                  }`}
                  aria-hidden
                />
                {gate.label}
              </span>
              <span className="text-muted">{gate.detail}</span>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}
