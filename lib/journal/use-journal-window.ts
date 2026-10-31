"use client";

import { useMemo } from "react";
import type { ComplianceSummary, JournalTradeView, LockoutWindow } from "@/lib/api/generated";
import { useApi } from "@/lib/api/use-api";

export interface JournalWindow {
  /** Null while loading, or after a failed load — never an empty array in those cases, so "nothing happened" and
   *  "we could not ask" stay distinguishable at the call site. */
  trades: JournalTradeView[] | null;
  /** How the window's trades respected the rules — judged by the core, against the rules and the lockouts *as they were*. */
  compliance: ComplianceSummary | null;
  lockouts: LockoutWindow[];
  /** The closed trades could not be read — distinct from "no trade". */
  failed: boolean;
  /** Why, in the core's own words, when `failed`. */
  error: Error | null;
}

/** `YYYY-MM-DD` → the instants the core's window takes: the first and the last millisecond of the days, UTC. */
export function windowBounds(fromDate: string, toDate: string): { start: string; end: string } {
  return { start: `${fromDate}T00:00:00.000Z`, end: `${toDate}T23:59:59.999Z` };
}

const TRADE_EVENTS = ["position.closed"] as const;
const LOCKOUT_EVENTS = ["risk.lockout_enabled", "risk.lockout_cleared", "risk.lockout_acknowledged"] as const;

/**
 * What every compliance-aware surface needs of a window: the closed trades (with the R multiple and the rules each one broke),
 * the compliance summary over them, and the lockouts that were open during it. Three reads of the core, nothing computed here.
 *
 * `wanted` says which of the three a surface actually draws — a surface that only draws the rate does not ask for the trades.
 * `/journal` and `/analyse` pick their own range; the top-bar figures and the discipline gauge use the fixed trailing window of
 * `useComplianceRate`, so the same figure means the same thing everywhere.
 *
 * Dates are `YYYY-MM-DD`. The lockouts are read up to the end of `toDate`, not up to now.
 */
export function useJournalWindow(
  accountId: string | null,
  fromDate: string | null,
  toDate: string | null,
  wanted: { trades?: boolean; compliance?: boolean; lockouts?: boolean } = { trades: true, compliance: true, lockouts: true },
): JournalWindow {
  const bounds = accountId && fromDate && toDate ? windowBounds(fromDate, toDate) : null;
  const window = bounds === null ? null : { accountId: accountId!, ...bounds };

  const trades = useApi(
    "journal_trades",
    window && wanted.trades ? { query: window } : null,
    { refreshOn: TRADE_EVENTS },
  );
  const compliance = useApi(
    "journal_compliance",
    window && wanted.compliance ? { query: window } : null,
    { refreshOn: TRADE_EVENTS },
  );
  const lockouts = useApi(
    "risk_lockouts",
    window && wanted.lockouts ? { query: { accountId: window.accountId, upTo: window.end } } : null,
    { refreshOn: LOCKOUT_EVENTS },
  );

  return useMemo(() => {
    const tradesFailed = Boolean(wanted.trades) && trades.error !== null && trades.data === null;
    const complianceFailed = Boolean(wanted.compliance) && compliance.error !== null && compliance.data === null;
    return {
      trades: trades.data,
      compliance: compliance.data,
      lockouts: lockouts.data?.history ?? [],
      failed: tradesFailed || complianceFailed,
      error: tradesFailed ? trades.error : complianceFailed ? compliance.error : null,
    };
  }, [trades.data, trades.error, compliance.data, compliance.error, lockouts.data, wanted.trades, wanted.compliance]);
}
