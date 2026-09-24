"use client";

import Link from "next/link";
import { ArrowRight, Target } from "lucide-react";
import { cn } from "cn";
import { useCockpit } from "@/lib/realtime/provider";
import { useComplianceRate } from "@/lib/compliance/use-compliance-rate";
import { VIOLATION_LABELS } from "@/lib/compliance/labels";
import type { ViolationType } from "@/lib/compliance/violations";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";

const TYPES: ViolationType[] = ["LOCKOUT_ACTIVE", "SESSION_WINDOW", "SIZE_POLICY"];

/**
 * T07 — the product's KPI (charter.md, principe 2: compliance, not P&L on a
 * noisy sample). It sat in the top bar where the P&L would otherwise be;
 * since the 2026-09-24 redesign it is the first card of the Command Center,
 * beside the verdict — the T07 success criterion, "affiché en haut du
 * cockpit", now read as the top of the cockpit's home screen.
 *
 * Same number as /risk's discipline gauge: one hook, one fetch
 * (lib/compliance/use-compliance-rate.ts).
 */
export function ComplianceCard({ className }: { className?: string }) {
  const { account } = useCockpit();
  const summary = useComplianceRate();
  const { rate, tradeCount, breachedCount, byType, lookbackDays, failed } = summary;

  // No trade on the window gives rate 1 — and a discipline screen reading
  // 100 % because it has nothing to read is worse than an empty one
  // (information_architecture.md). Nothing measured, nothing shown.
  const measured = rate !== null && tradeCount > 0;
  const percent = measured ? Math.round(rate * 100) : null;
  const tone = !measured ? "muted" : rate >= 0.9 ? "profit" : rate >= 0.7 ? "warning" : "loss";
  const valueClass =
    tone === "profit" ? "text-primary" : tone === "warning" ? "text-warning" : tone === "loss" ? "text-loss" : "text-foreground";
  const bar =
    tone === "warning"
      ? { track: "bg-warning/15", bar: "bg-warning" }
      : tone === "loss"
        ? { track: "bg-loss/15", bar: "bg-loss" }
        : { track: "bg-primary/15", bar: "bg-primary" };

  return (
    <Card className={cn("surface-card gap-5 rounded-2xl px-6 py-6 shadow-none", className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-xl bg-muted text-primary ring-1 ring-border">
            <Target className="size-5" strokeWidth={1.75} />
          </span>
          <div>
            <p className="text-sm font-medium text-foreground">Conformité au plan</p>
            <p className="text-xs text-muted-foreground">{lookbackDays} derniers jours</p>
          </div>
        </div>
        <Link href="/risk" className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground">
          Détail
          <ArrowRight className="size-3.5" />
        </Link>
      </div>

      <div>
        <p className={cn("tnum text-5xl font-light tracking-tight", valueClass)}>
          {percent === null ? "—" : `${percent} %`}
        </p>
        <p className="mt-2 text-xs text-muted-foreground">
          {!account
            ? "pas de compte connecté"
            : failed
              ? "trades clôturés illisibles — le backend répond-il ?"
              : rate === null
                ? "lecture des trades clôturés…"
                : !measured
                  ? "aucun trade clôturé sur la période — rien à mesurer"
                  : `${tradeCount - breachedCount} trade(s) dans le cadre sur ${tradeCount}`}
        </p>
        {percent !== null && (
          <Progress value={percent} className={cn("mt-4 h-1.5", bar.track)} indicatorClassName={bar.bar} />
        )}
      </div>

      <ul className="flex flex-col gap-2 border-t border-border pt-4 text-xs">
        {TYPES.map((type) => (
          <li key={type} className="flex items-center justify-between gap-3">
            <span className={byType[type] > 0 ? "text-foreground" : "text-muted-foreground"}>
              {VIOLATION_LABELS[type]}
            </span>
            <span className={cn("tnum", byType[type] > 0 ? "text-loss" : "text-muted-foreground")}>
              {byType[type]}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
