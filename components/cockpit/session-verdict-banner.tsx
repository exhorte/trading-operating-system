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
 * The verdict itself has the top of the page, and the detail stays one click
 * away on /preflight (T09), which is the screen that owns it. Every gate is
 * listed as a chip, so « why » is readable without a click. The state is
 * carried by the icon, the words AND the colour — never by colour alone.
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
    return <Skeleton className={cn("h-[16.25rem] rounded-xl", className)} />;
  }

  const { armed, blocking, lockoutReason } = sessionVerdict(risk);
  const Icon = armed ? ShieldCheck : ShieldX;

  return (
    <Card className={cn("gap-6 px-6 py-6 transition-opacity", untrusted && "opacity-60", className)}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-4">
          <span
            className={cn(
              "flex size-12 shrink-0 items-center justify-center rounded-xl border",
              armed ? "border-success/25 bg-success/10 text-success" : "border-destructive/25 bg-destructive/10 text-destructive",
            )}
          >
            <Icon className="size-6" strokeWidth={1.75} aria-hidden="true" />
          </span>
          <div>
            <p className="text-sm text-muted-foreground">Verdict de séance</p>
            <p
              className={cn(
                "text-3xl font-semibold tracking-tight sm:text-4xl",
                armed ? "text-success" : "text-destructive",
              )}
            >
              {armed ? "Armé" : "Pas armé"}
            </p>
          </div>
        </div>
        {showPreflightLink && (
          <Button asChild variant="outline" size="sm">
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
            Lockout : <span className="font-medium text-destructive">{lockoutReason}</span>
            {blocking.length > 0 && ` · ${blocking.length} point(s) bloquant(s)`}
          </>
        ) : (
          <>
            <span className="font-medium text-destructive">{blocking[0]?.label ?? "Compte verrouillé"}</span>
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
                  "flex items-center gap-2 rounded-lg border px-3 py-2 text-xs",
                  open ? "bg-muted/50" : "border-destructive/30 bg-destructive/5",
                )}
              >
                <span
                  className={cn("size-1.5 shrink-0 rounded-full", open ? "bg-success" : "bg-destructive")}
                  aria-hidden="true"
                />
                <span className="truncate">{gate.label}</span>
                <span className="sr-only">{open ? " : au vert" : " : bloquant"}</span>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
