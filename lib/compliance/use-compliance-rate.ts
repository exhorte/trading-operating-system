"use client";

import { useMemo } from "react";
import type { LockoutWindow, ViolationType } from "@/lib/api/generated";
import { useCockpit } from "@/lib/realtime/provider";
import { useJournalWindow } from "@/lib/journal/use-journal-window";

export interface ComplianceWindow {
  /** 0..1 as the core computed it, or null while it is being read or could not be. */
  rate: number | null;
  tradeCount: number;
  /** Trades carrying at least one violation. */
  breachedCount: number;
  /** Occurrences per violation type — the attribution axis. Every type is present, zero included. */
  byType: Record<ViolationType, number>;
  /** Lockout windows returned by the same window; ordering left to the caller. */
  lockouts: LockoutWindow[];
  /** Number of days the trailing window covers. */
  lookbackDays: number;
  /** The closed trades could not be read — distinct from "no trade". */
  failed: boolean;
}

const NO_VIOLATIONS: Record<ViolationType, number> = { LOCKOUT_ACTIVE: 0, SESSION_WINDOW: 0, SIZE_POLICY: 0 };

/**
 * T07's compliance rate over a fixed trailing window.
 *
 * The window is deliberately independent of whatever range `/journal` or `/analyse` happens to show: the figure must mean the
 * same thing on every screen. The judging is the core's (`GET /api/journal/compliance`); this hook is only the trailing-window
 * policy, so the Command Center, the discipline gauge and the lockout history all read one result.
 */
export function useComplianceRate(lookbackDays = 7): ComplianceWindow {
  const { activeAccountId } = useCockpit();

  // Computed once per mount: the window only moves at midnight, and recomputing it on every render would re-ask on every frame.
  const { fromDate, toDate } = useMemo(() => {
    const to = new Date();
    const from = new Date(to.getTime() - lookbackDays * 24 * 60 * 60 * 1000);
    return { fromDate: from.toISOString().slice(0, 10), toDate: to.toISOString().slice(0, 10) };
  }, [lookbackDays]);

  const { compliance, lockouts, failed } = useJournalWindow(activeAccountId, fromDate, toDate, {
    compliance: true,
    lockouts: true,
  });

  return useMemo(
    () => ({
      rate: compliance === null ? null : compliance.rate,
      tradeCount: compliance?.tradeCount ?? 0,
      breachedCount: compliance?.breachedCount ?? 0,
      byType: { ...NO_VIOLATIONS, ...(compliance?.byType as Partial<Record<ViolationType, number>> | undefined) },
      lockouts,
      lookbackDays,
      failed,
    }),
    [compliance, lockouts, lookbackDays, failed],
  );
}
