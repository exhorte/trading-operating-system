"use client";

import { useEffect, useState } from "react";
import { backendHttpBase } from "@/lib/realtime/backend-url";
import type { LockoutWindow } from "@/lib/compliance/violations";
import type { JournalTrade } from "./types";

export interface JournalWindow {
  /** Null while loading, or after a failed load — never an empty array in
   *  those cases, so "nothing happened" and "we could not ask" stay
   *  distinguishable at the call site. */
  trades: JournalTrade[] | null;
  lockouts: LockoutWindow[];
  failed: boolean;
}

/**
 * One fetch of the two things every compliance-aware surface needs: the
 * closed trades of a window, and the lockouts that were open during it.
 *
 * Extracted on 2026-09-20 when the account analysis screen would have been
 * the third copy of this pair (after `ComplianceBadge` and `/journal`). The
 * badge and the discipline gauge read it through `useComplianceRate`;
 * `/analyse` reads it directly with its own range.
 *
 * `/journal`'s page deliberately keeps its own fetch: it also pulls setup
 * proposals and carries a different error surface. Migrating it is a
 * separate change, not a side effect of this one.
 *
 * Dates are `YYYY-MM-DD`, matching what the endpoint takes. The lockout
 * query is anchored at the end of `toDate` rather than at "now": the
 * endpoint selects `since <= to`, so the only rows the difference could add
 * are lockouts stamped in the future, which do not exist.
 */
export function useJournalWindow(
  accountId: string | null,
  fromDate: string | null,
  toDate: string | null,
): JournalWindow {
  const [trades, setTrades] = useState<JournalTrade[] | null>(null);
  const [lockouts, setLockouts] = useState<LockoutWindow[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!accountId || !fromDate || !toDate) {
      return;
    }
    let cancelled = false;

    async function load() {
      const base = backendHttpBase();
      const account = encodeURIComponent(accountId!);
      try {
        const [tradesRes, lockoutsRes] = await Promise.all([
          fetch(`${base}/api/journal/trades?accountId=${account}&from=${fromDate}&to=${toDate}`),
          fetch(
            `${base}/api/risk/lockouts?accountId=${account}` +
              `&to=${encodeURIComponent(`${toDate}T23:59:59.999Z`)}`,
          ),
        ]);
        if (cancelled) {
          return;
        }
        setFailed(false);
        setTrades(tradesRes.ok ? ((await tradesRes.json()) as JournalTrade[]) : []);
        setLockouts(lockoutsRes.ok ? ((await lockoutsRes.json()) as LockoutWindow[]) : []);
      } catch {
        if (!cancelled) {
          setTrades(null);
          setFailed(true);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [accountId, fromDate, toDate]);

  return { trades, lockouts, failed };
}
