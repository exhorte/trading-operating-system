"use client";

import type { LucideIcon } from "lucide-react";
import {
  ArrowDownToLine,
  ArrowLeftRight,
  CalendarClock,
  Clock,
  Cpu,
  Hash,
  Layers,
  Repeat,
  TrendingDown,
} from "lucide-react";
import { cn } from "cn";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import type { RiskGate } from "@/lib/contracts/snapshots";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { SessionVerdictBanner } from "@/components/cockpit/session-verdict-banner";

/** One recognisable icon per gate; an unknown id still renders, with a neutral one. */
const GATE_ICONS: Record<string, LucideIcon> = {
  "gate-daily-loss": TrendingDown,
  "gate-total-dd": ArrowDownToLine,
  "gate-open-risk": Layers,
  "gate-max-trades": Hash,
  "gate-consec-loss": Repeat,
  "gate-spread": ArrowLeftRight,
  "gate-session": Clock,
  "gate-news": CalendarClock,
  "gate-connection": Cpu,
};

function GateCard({ gate, untrusted }: { gate: RiskGate; untrusted: boolean }) {
  const open = gate.state === "open";
  const Icon = GATE_ICONS[gate.gateId] ?? Hash;
  return (
    <Card
      className={cn(
        "surface-card gap-4 rounded-2xl px-5 py-5 shadow-none transition-opacity",
        !open && "surface-glow-loss ring-1 ring-loss/30",
        untrusted && "opacity-60",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <span
          className={cn(
            "flex size-10 shrink-0 items-center justify-center rounded-xl ring-1",
            open ? "bg-muted text-primary ring-border" : "bg-loss/12 text-loss ring-loss/30",
          )}
        >
          <Icon className="size-5" strokeWidth={1.75} />
        </span>
        <StatusPill tone={open ? "profit" : "loss"} pulse={!open}>
          {open ? "Au vert" : "Bloquant"}
        </StatusPill>
      </div>
      <div>
        <p className="text-sm font-medium text-foreground">{gate.label}</p>
        <p className={cn("mt-1 text-xs leading-snug", open ? "text-muted-foreground" : "text-loss")}>
          {gate.detail}
        </p>
      </div>
    </Card>
  );
}

/**
 * T09 — the pre-session ritual in one page: every item the system can check
 * for itself, plus a single armed / not-armed verdict.
 *
 * Reads the risk state that already exists (lib/risk/evaluate.ts runs these
 * gates on every tick); it does not evaluate anything of its own. Nothing
 * here is checkable by hand on purpose — "pas un document à cocher"
 * (context/product/tools/T09-checklist-prevol.md). An item is green because
 * the system verified it, or it is not green.
 *
 * 2026-09-24 redesign: the verdict is the same hero card as the Command
 * Center's (same rule, lib/cockpit/verdict.ts), and every gate gets its own
 * card — icon, state, detail — instead of one dense list.
 */
export default function PreflightPage() {
  const { risk } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (!risk) {
    return (
      <div className="flex flex-col gap-5">
        <Skeleton className="h-[160px] rounded-2xl" />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 9 }).map((_, index) => (
            <Skeleton key={index} className="h-[132px] rounded-2xl" />
          ))}
        </div>
      </div>
    );
  }

  const blockingCount = risk.gates.filter((gate) => gate.state !== "open").length;

  return (
    <div className="flex flex-col gap-5">
      <SessionVerdictBanner showPreflightLink={false} showGates={false} />

      <section className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-sm font-medium text-foreground">Points vérifiés</h2>
          <p className="text-xs text-muted-foreground">
            {risk.gates.length - blockingCount} sur {risk.gates.length} au vert
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {risk.gates.map((gate) => (
            <GateCard key={gate.gateId} gate={gate} untrusted={untrusted} />
          ))}
        </div>
      </section>

      {/* Stated here, not only in the fiche: the 6 trades opened during active
          lockouts on 2026-09-14/15 went straight through MT5 and this page
          would not have stopped any of them. Better to say so where the
          verdict is read than to let "Armé" imply more than it means. */}
      <p className="text-xs text-muted-foreground">
        Ce verdict porte sur ce qui passe par ce système. Un ordre saisi
        directement dans MT5 n&apos;est contraint par aucun de ces points.
      </p>
    </div>
  );
}
