"use client";

import type { SignalStatus } from "@/lib/contracts/enums";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatClockTime } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

const STATUS_TONES: Record<SignalStatus, PillTone> = {
  detected: "info",
  scored: "info",
  risk_review: "warning",
  approved: "profit",
  rejected: "loss",
  commanded: "accent",
  acknowledged: "accent",
  reported: "muted",
  expired: "muted",
};

export function SignalQueue() {
  const { signals, connection } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (connection === "connecting") {
    return (
      <Card title="Signal queue">
        <Skeleton className="h-40" />
      </Card>
    );
  }

  return (
    <Card title="Signal queue" untrusted={untrusted}>
      {signals.length === 0 ? (
        <p className="py-6 text-center text-xs text-muted">No signals yet.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {signals.slice(0, 6).map((signal) => (
            <li
              key={signal.signalId}
              className="rounded border border-border bg-surface-elevated p-2"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-xs font-medium">
                  <span className="tnum text-muted">{signal.signalId}</span>
                  {signal.symbol}
                  <span className={signal.side === "buy" ? "text-profit" : "text-loss"}>
                    {signal.side.toUpperCase()}
                  </span>
                </span>
                <StatusPill tone={STATUS_TONES[signal.status]}>{signal.status}</StatusPill>
              </div>
              <p className="mt-1 text-[11px] text-muted">{signal.contextSummary}</p>
              <div className="mt-1 flex items-center justify-between text-[10px] text-muted">
                <span>
                  {signal.strategyId} · score{" "}
                  <span className="tnum text-foreground">
                    {signal.score}/{signal.maxScore}
                  </span>
                </span>
                <span>{formatClockTime(signal.createdAt)}</span>
              </div>
              {signal.riskDecision && (
                <p className="mt-1 text-[10px] text-muted">Risk: {signal.riskDecision}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
