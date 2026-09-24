"use client";

import { useCockpit, useDismissLockoutViolation } from "@/lib/realtime/provider";

/**
 * T02c — a position opened while a lockout was already active, flagged the
 * instant the Gateway detects it (journal.lockout_violated), not only after
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
    <div className="flex shrink-0 flex-col gap-2 border-b border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning md:px-6">
      {lockoutViolations.map((violation) => (
        <div key={violation.brokerPositionId} className="flex items-center justify-between gap-3">
          <span>
            <strong>Position ouverte pendant un lockout actif.</strong> {violation.symbol}{" "}
            {violation.side}, position {violation.brokerPositionId}, verrou «{" "}
            {violation.lockoutReason} ».
          </span>
          <button
            type="button"
            onClick={() => dismiss(violation.brokerPositionId)}
            className="shrink-0 rounded-lg bg-warning/15 px-3.5 py-1.5 text-xs font-medium text-warning ring-1 ring-warning/40 transition-colors hover:bg-warning/25"
          >
            Vu
          </button>
        </div>
      ))}
    </div>
  );
}
