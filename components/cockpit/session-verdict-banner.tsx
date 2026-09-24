"use client";

import Link from "next/link";
import { ArrowRight, ShieldCheck, ShieldX } from "lucide-react";
import { cn } from "cn";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { sessionVerdict } from "@/lib/cockpit/verdict";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * The first thing the eye lands on: can I open a position right now?
 *
 * The Command Center used to answer this only by inference — a "Risk state:
 * NORMAL" tile among seven others, plus nine gate rows in a side panel. The
 * verdict itself has the top of the page, and the detail stays one click
 * away on /preflight (T09), which is the screen that owns it.
 *
 * 2026-09-24: the hero card of the redesign, in the place of the reference
 * mock-up's equity card — the glow says the answer (mint armed, coral not),
 * and every gate is listed as a chip, so "why" is readable without a click.
 *
 * Same rule as /preflight, imported rather than re-derived
 * (lib/cockpit/verdict.ts).
 */
export function SessionVerdictBanner({
  className,
  showPreflightLink = true,
  showGates = true,
}: {
  className?: string;
  /** Off on /preflight itself. */
  showPreflightLink?: boolean;
  /** Off where the gates are detailed right below (/preflight). */
  showGates?: boolean;
}) {
  const { risk } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (!risk) {
    return <Skeleton className={cn("h-[260px] rounded-2xl", className)} />;
  }

  const { armed, blocking, lockoutReason } = sessionVerdict(risk);
  const Icon = armed ? ShieldCheck : ShieldX;

  return (
    <Card
      className={cn(
        "gap-6 rounded-2xl px-6 py-6 shadow-none transition-opacity",
        armed ? "surface-glow" : "surface-glow-loss",
        untrusted && "opacity-60",
        className,
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-4">
          <span
            className={cn(
              "flex size-12 shrink-0 items-center justify-center rounded-2xl ring-1",
              armed ? "bg-primary/12 text-primary ring-primary/25" : "bg-loss/12 text-loss ring-loss/30",
            )}
          >
            <Icon className="size-6" strokeWidth={1.75} />
          </span>
          <div>
            <p className="text-[13px] text-muted-foreground">Verdict de séance</p>
            <p className={cn("text-4xl font-light tracking-tight", armed ? "text-primary" : "text-loss")}>
              {armed ? "Armé" : "Pas armé"}
            </p>
          </div>
        </div>
        {showPreflightLink && (
          <Button asChild variant="outline" size="sm" className="rounded-lg">
            <Link href="/preflight">
              Pré-vol
              <ArrowRight />
            </Link>
          </Button>
        )}
      </div>

      <p className="text-sm text-muted-foreground">
        {armed ? (
          `${risk.gates.length} points vérifiables au vert — la séance peut commencer.`
        ) : lockoutReason ? (
          <>
            Lockout : <span className="text-loss">{lockoutReason}</span>
            {blocking.length > 0 && ` · ${blocking.length} point(s) bloquant(s)`}
          </>
        ) : (
          <>
            <span className="text-loss">{blocking[0]?.label ?? "Compte verrouillé"}</span>
            {blocking[0]?.detail ? ` — ${blocking[0].detail}` : ""}
            {blocking.length > 1 && ` · +${blocking.length - 1} autre(s)`}
          </>
        )}
      </p>

      {showGates && (
        <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {risk.gates.map((gate) => {
            const open = gate.state === "open";
            return (
              <li
                key={gate.gateId}
                title={gate.detail}
                className={cn(
                  "flex items-center gap-2 rounded-xl px-3 py-2 text-xs ring-1",
                  open ? "bg-muted/60 text-foreground/85 ring-border" : "bg-loss/10 text-loss ring-loss/30",
                )}
              >
                <span className={cn("size-1.5 shrink-0 rounded-full", open ? "bg-profit" : "bg-loss")} aria-hidden />
                <span className="truncate">{gate.label}</span>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
