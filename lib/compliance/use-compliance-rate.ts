"use client";

import { useMemo } from "react";
import { useCockpit } from "@/lib/realtime/provider";
import { useJournalWindow } from "@/lib/journal/use-journal-window";
import { emptyComplianceSummary, summarizeCompliance, type ComplianceSummary } from "./summarize";
import type { LockoutWindow } from "./violations";

export interface ComplianceWindow extends ComplianceSummary {
  /** Lockout windows returned by the same fetch; ordering left to the caller. */
  lockouts: LockoutWindow[];
  /** Number of days the trailing window covers. */
  lookbackDays: number;
}

/**
 * T07's compliance rate over a fixed trailing window.
 *
 * The window is deliberately independent of whatever range `/journal` or
 * `/analyse` happens to show: the top-bar badge must mean the same thing on
 * every screen. Fetching lives in `useJournalWindow`, the arithmetic in
 * `summarizeCompliance` — this hook is only the trailing-window policy that
 * binds them, so the badge, the discipline gauge and the lockout history all
 * read one result from one fetch.
 */
export function useComplianceRate(lookbackDays = 7): ComplianceWindow {
  const { account } = useCockpit();
  const accountId = account?.accountId ?? null;
  const balance = account?.balance ?? null;

  // Computed once per mount, as the previous inline version was: the window
  // only moves at midnight, and recomputing it on every render would refire
  // the fetch on every tick of the realtime stream.
  const { fromDate, toDate } = useMemo(() => {
    const to = new Date();
    const from = new Date(to.getTime() - lookbackDays * 24 * 60 * 60 * 1000);
    return { fromDate: from.toISOString().slice(0, 10), toDate: to.toISOString().slice(0, 10) };
  }, [lookbackDays]);

  const { trades, lockouts } = useJournalWindow(accountId, fromDate, toDate);

  return useMemo(() => {
    if (!accountId || !trades) {
      return { ...emptyComplianceSummary(), lockouts, lookbackDays };
    }
    return {
      ...summarizeCompliance(accountId, trades, lockouts, balance),
      lockouts,
      lookbackDays,
    };
  }, [accountId, trades, lockouts, balance, lookbackDays]);
}
