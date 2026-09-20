"use client";

import Link from "next/link";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { sessionVerdict } from "@/lib/cockpit/verdict";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * The first thing the eye lands on: can I open a position right now?
 *
 * The Command Center used to answer this only by inference — a "Risk state:
 * NORMAL" tile among seven others, plus nine gate rows in a side panel. The
 * verdict itself now has the top of the page, and the detail stays one click
 * away on /preflight (T09), which is the screen that owns it.
 *
 * Same rule as /preflight, imported rather than re-derived
 * (lib/cockpit/verdict.ts).
 */
export function SessionVerdictBanner() {
  const { risk } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (!risk) {
    return <Skeleton className="h-[68px]" />;
  }

  const { armed, blocking, lockoutReason } = sessionVerdict(risk);

  const frameClass = armed
    ? "border-profit/40 bg-profit/5"
    : "border-loss/50 bg-loss/10";

  return (
    <section
      className={`flex items-center justify-between gap-4 rounded-lg border px-4 py-3 ${frameClass} ${
        untrusted ? "opacity-60" : ""
      }`}
    >
      <div className="flex items-center gap-3">
        <span
          className={`h-2.5 w-2.5 shrink-0 rounded-full ${
            armed ? "bg-profit" : "animate-pulse bg-loss"
          }`}
          aria-hidden
        />
        <div>
          <p
            className={`text-lg font-semibold tracking-tight ${
              armed ? "text-profit" : "text-loss"
            }`}
          >
            {armed ? "Armé" : "Pas armé"}
          </p>
          <p className="text-xs text-muted">
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
        </div>
      </div>
      <Link
        href="/preflight"
        className="shrink-0 rounded border border-border bg-surface-elevated px-2.5 py-1 text-xs text-muted transition-colors hover:text-foreground"
      >
        Pré-vol →
      </Link>
    </section>
  );
}
