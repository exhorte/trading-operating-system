"use client";

import type { LucideIcon } from "lucide-react";
import {
  ArrowDownToLine,
  ArrowLeftRight,
  CalendarClock,
  CircleCheck,
  Clock,
  Cpu,
  Hash,
  Layers,
  Lock,
  OctagonX,
  Repeat,
  TrendingDown,
} from "lucide-react";
import { cn } from "cn";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import type { RiskGate } from "@/lib/contracts/snapshots";
import { sessionVerdict } from "@/lib/cockpit/verdict";
import { SessionVerdictBanner } from "@/components/cockpit/session-verdict-banner";
import { PageHeader } from "@/components/shell/page-header";
import { screenAt } from "@/components/shell/nav";
import { Callout } from "@/components/ui/callout";
import { Card } from "@/components/ui/card";
import { HighlightBar, MetricPanel, MetricPanelItem } from "@/components/ui/metric-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { SplitLayout } from "@/components/ui/split-layout";
import { StatusPill } from "@/components/ui/status-pill";

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
        "gap-4 px-5 py-5 transition-opacity",
        !open && "border-destructive/30 bg-destructive/5",
        untrusted && "opacity-60",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <span
          className={cn(
            "flex size-10 shrink-0 items-center justify-center rounded-lg border bg-background shadow-xs",
            !open && "border-destructive/30 text-destructive",
          )}
        >
          <Icon className="size-5" strokeWidth={1.75} aria-hidden="true" />
        </span>
        <StatusPill tone={open ? "profit" : "loss"} pulse={!open}>
          {open ? "Au vert" : "Bloquant"}
        </StatusPill>
      </div>
      <div>
        <p className="text-sm font-semibold">{gate.label}</p>
        <p className="mt-1 text-sm leading-snug text-muted-foreground">{gate.detail}</p>
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
 * Composition (ADR 0017): the verdict and its nine gates on the left, the
 * dark panel counting them on the right, and the « Important » note — what
 * this verdict does NOT cover — stated where the verdict is read.
 */
export default function PreflightPage() {
  const { risk } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (!risk) {
    return (
      <div className="flex flex-col gap-10">
        <SplitLayout
          main={
            <>
              <PageHeader screen={screenAt("/preflight")} />
              <Skeleton className="h-[160px] rounded-xl" />
              <div className="grid gap-4 sm:grid-cols-2">
                {Array.from({ length: 6 }).map((_, index) => (
                  <Skeleton key={index} className="h-[132px] rounded-xl" />
                ))}
              </div>
            </>
          }
          aside={<Skeleton className="h-[320px] rounded-xl" />}
        />
      </div>
    );
  }

  const { armed, blocking, lockoutReason } = sessionVerdict(risk);
  const greenCount = risk.gates.length - blocking.length;

  return (
    <div className="flex flex-col gap-10">
      <SplitLayout
        main={
          <>
            <PageHeader screen={screenAt("/preflight")} />
            <SessionVerdictBanner showPreflightLink={false} showGates={false} />
            <div className="grid gap-4 sm:grid-cols-2">
              {risk.gates.map((gate) => (
                <GateCard key={gate.gateId} gate={gate} untrusted={untrusted} />
              ))}
            </div>
          </>
        }
        aside={
          <>
            <HighlightBar
              icon={CircleCheck}
              value={`${greenCount} / ${risk.gates.length}`}
              label="points au vert"
              className={untrusted ? "opacity-60" : undefined}
            />
            <MetricPanel>
              <MetricPanelItem
                label="Verdict de séance"
                value={armed ? "Armé" : "Pas armé"}
                tone={armed ? "success" : "destructive"}
                hint={armed ? "tout ce que le système vérifie est au vert" : "au moins un point bloque la séance"}
                icon={CircleCheck}
                solidIcon
                untrusted={untrusted}
              />
              <MetricPanelItem
                label="Points bloquants"
                value={String(blocking.length)}
                tone={blocking.length > 0 ? "destructive" : undefined}
                hint={blocking[0] ? `${blocking[0].label}${blocking.length > 1 ? ` · +${blocking.length - 1}` : ""}` : "aucun"}
                icon={OctagonX}
                untrusted={untrusted}
              />
              <MetricPanelItem
                label="Verrou"
                value={lockoutReason ? "Actif" : "Aucun"}
                tone={lockoutReason ? "destructive" : undefined}
                hint={lockoutReason ?? "aucun lockout enregistré pour ce compte"}
                icon={Lock}
                untrusted={untrusted}
              />
            </MetricPanel>
          </>
        }
      />

      {/* Stated here, not only in the fiche: the 6 trades opened during active
          lockouts on 2026-09-14/15 went straight through MT5 and this page
          would not have stopped any of them. Better to say so where the
          verdict is read than to let "Armé" imply more than it means. */}
      <Callout title="Important">
        Ce verdict porte sur ce qui passe par ce système. Un ordre saisi directement dans MT5 n&apos;est contraint par
        aucun de ces points.
      </Callout>
    </div>
  );
}
