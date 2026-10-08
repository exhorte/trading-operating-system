"use client";

import { useEffect, useState } from "react";
import { ListChecks } from "lucide-react";
import { cn } from "cn";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";

/** T02b: mm:ss remaining on a timed pause; "0:00" once it has run out (the
 *  ledger clearance — not this display — is what actually lifts the lock). */
function formatCountdown(untilIso: string, nowMs: number): string {
  const remainingMs = Math.max(0, Date.parse(untilIso) - nowMs);
  const totalSeconds = Math.floor(remainingMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

/** T02b: the only genuinely new UI piece — everything else (banner, ledger)
 *  already exists since T02a. */
function LockoutCountdown({ until }: { until: string }) {
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const interval = setInterval(() => setNowMs(Date.now()), 1_000);
    return () => clearInterval(interval);
  }, []);

  return <span className="tabular-nums">Reprise dans {formatCountdown(until, nowMs)}</span>;
}

/**
 * The gates the Risk Engine runs on every tick, one line each (state dot,
 * label, detail), and the lockout notice with its countdown when a pause is
 * running. The numbers — daily loss, drawdown, trades, streak — are in the
 * dark panel beside it (RiskMetrics).
 */
export function RiskGatesPanel() {
  const { risk } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (!risk) {
    return (
      <Panel title="Points de contrôle" icon={ListChecks}>
        <Skeleton className="h-40" />
      </Panel>
    );
  }

  const tone = risk.state === "normal" ? "profit" : risk.state === "warning" ? "warning" : "loss";

  return (
    <Panel
      title="Points de contrôle"
      description="ce que le Risk Engine évalue à chaque tick"
      icon={ListChecks}
      untrusted={untrusted}
      actions={<StatusPill tone={tone}>{risk.state}</StatusPill>}
    >
      <div className="flex flex-col gap-4">
        {risk.lockoutReason && (
          <p className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm">
            <span>
              <strong className="text-destructive">Lockout</strong> : {risk.lockoutReason}
            </span>
            {risk.lockoutUntil && <LockoutCountdown until={risk.lockoutUntil} />}
          </p>
        )}
        <ul className="flex flex-col divide-y">
          {risk.gates.map((gate) => (
            <li key={gate.gateId} className="flex items-center justify-between gap-3 py-2 text-sm first:pt-0 last:pb-0">
              <span className="flex min-w-0 items-center gap-2">
                <span
                  className={cn("size-1.5 shrink-0 rounded-full", gate.state === "open" ? "bg-success" : "bg-warning")}
                  aria-hidden="true"
                />
                <span className="truncate">{gate.label}</span>
                <span className="sr-only">{gate.state === "open" ? " : au vert" : " : bloquant"}</span>
              </span>
              <span className="shrink-0 text-muted-foreground">{gate.detail}</span>
            </li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}
