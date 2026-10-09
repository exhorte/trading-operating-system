"use client";

import { TriangleAlert } from "lucide-react";
import { useCockpit, useDismissLockoutViolation } from "@/lib/realtime/provider";
import { Button } from "@/components/ui/button";

/**
 * T02c — a position opened while a lockout was already active, flagged the
 * instant the core detects it (journal.lockout_violated), not only after
 * the fact in /journal (T07). Distinct from LockoutAckBanner on purpose: that
 * one says "you are locked right now"; this one says "a lockout was just
 * bypassed" — a fact that already happened and can't be undone, so dismissing
 * it is local only, never a clear on the ledger (T07/`/journal` keeps the
 * permanent record).
 */
export function LockoutViolationBanner() {
  const { lockoutViolations } = useCockpit();
  const dismiss = useDismissLockoutViolation();

  if (lockoutViolations.length === 0) {
    return null;
  }

  return (
    <div role="alert" className="border-b border-warning/30 bg-warning/10 px-4 sm:px-6 lg:px-10">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-2 py-3 text-sm">
        {lockoutViolations.map((violation) => (
          <div key={violation.brokerPositionId} className="flex flex-wrap items-center justify-between gap-3">
            <p className="flex min-w-0 items-start gap-2">
              <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
              <span>
                <strong className="text-warning">Position ouverte pendant un lockout actif.</strong>{" "}
                {violation.symbol} {violation.side}, position {violation.brokerPositionId}, verrou «{" "}
                {violation.lockoutReason} ».
              </span>
            </p>
            <Button variant="outline" size="sm" onClick={() => dismiss(violation.brokerPositionId)}>
              Vu
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}
