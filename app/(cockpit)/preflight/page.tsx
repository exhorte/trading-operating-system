"use client";

import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { sessionVerdict } from "@/lib/cockpit/verdict";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";

/**
 * T09 — the pre-session ritual in one page: every item the system can check
 * for itself, plus a single armed / not-armed verdict.
 *
 * Reads the risk state that already exists (lib/risk/evaluate.ts runs these
 * gates on every tick); it does not evaluate anything of its own. Nothing
 * here is checkable by hand on purpose — "pas un document à cocher"
 * (context/product/tools/T09-checklist-prevol.md). An item is green because
 * the system verified it, or it is not green.
 */
export default function PreflightPage() {
  const { risk } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (!risk) {
    return (
      <Card title="Pré-vol">
        <Skeleton className="h-64" />
      </Card>
    );
  }

  // Same rule as the Command Center's verdict banner, imported rather than
  // re-derived — this page owns the detail, not a second definition of
  // "armed" (lib/cockpit/verdict.ts).
  const { armed, blocking } = sessionVerdict(risk);

  return (
    <div className="flex flex-col gap-4">
      <Card
        title="Pré-vol"
        untrusted={untrusted}
        actions={
          <StatusPill tone={armed ? "profit" : "loss"} pulse={!armed}>
            {armed ? "Armé" : "Pas armé"}
          </StatusPill>
        }
      >
        {armed ? (
          <p className="text-sm text-muted">
            Tous les points vérifiables sont au vert. La séance peut commencer.
          </p>
        ) : (
          <div className="flex flex-col gap-1.5">
            <p className="text-sm text-loss">
              {blocking.length === 0
                ? "Compte verrouillé."
                : `${blocking.length} point(s) bloquant(s).`}
            </p>
            {risk.lockoutReason && (
              <p className="rounded border border-loss/40 bg-loss/10 px-2 py-1 text-xs text-loss">
                Lockout : {risk.lockoutReason}
              </p>
            )}
            <ul className="flex flex-col gap-0.5 text-xs text-muted">
              {blocking.map((gate) => (
                <li key={gate.gateId}>
                  <span className="text-foreground">{gate.label}</span> — {gate.detail}
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      <Card title="Points vérifiés">
        <ul className="flex flex-col gap-1.5">
          {risk.gates.map((gate) => (
            <li key={gate.gateId} className="flex items-center justify-between gap-2 text-xs">
              <span className="flex items-center gap-1.5">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    gate.state === "open" ? "bg-profit" : "bg-loss"
                  }`}
                  aria-hidden
                />
                {gate.label}
              </span>
              <span className="text-muted">{gate.detail}</span>
            </li>
          ))}
        </ul>
      </Card>

      {/* Stated here, not only in the fiche: the 6 trades opened during active
          lockouts on 2026-09-14/15 went straight through MT5 and this page
          would not have stopped any of them. Better to say so where the
          verdict is read than to let "Armé" imply more than it means. */}
      <p className="text-xs text-muted">
        Ce verdict porte sur ce qui passe par ce système. Un ordre saisi
        directement dans MT5 n&apos;est contraint par aucun de ces points.
      </p>
    </div>
  );
}
