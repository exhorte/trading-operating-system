"use client";

import { useMemo } from "react";
import { useCockpit } from "@/lib/realtime/provider";
import { useJournalWindow } from "@/lib/journal/use-journal-window";
import type { JournalTrade } from "@/lib/journal/types";
import {
  emptyComplianceSummary,
  summarizeCompliance,
  type ComplianceSummary,
} from "@/lib/compliance/summarize";
import {
  accountBreakdowns,
  generalStats,
  tradingDayStats,
  type AccountBreakdowns,
  type GeneralStats,
  type TradingDayStats,
} from "./breakdowns";

export interface AccountAnalysis {
  loading: boolean;
  failed: boolean;
  /** Empty while loading — check `loading` before reading anything else. */
  trades: JournalTrade[];
  general: GeneralStats;
  tradingDays: TradingDayStats;
  breakdowns: AccountBreakdowns;
  compliance: ComplianceSummary;
}

/**
 * Everything `/analyse` shows, for one date range.
 *
 * Its own fetch, over the range the trader picked — unlike `useComplianceRate`,
 * whose window is a fixed trailing 7 days on purpose so the top-bar badge
 * means the same thing everywhere. Both call the same fetch hook and the same
 * pure summariser; only the window differs.
 */
export function useAccountAnalysis(fromDate: string, toDate: string): AccountAnalysis {
  const { account } = useCockpit();
  const accountId = account?.accountId ?? null;
  const balance = account?.balance ?? null;

  const { trades, lockouts, failed } = useJournalWindow(accountId, fromDate, toDate);

  return useMemo(() => {
    const rows = trades ?? [];
    return {
      loading: accountId !== null && trades === null && !failed,
      failed,
      trades: rows,
      general: generalStats(rows),
      tradingDays: tradingDayStats(rows),
      breakdowns: accountBreakdowns(rows),
      compliance: accountId
        ? summarizeCompliance(accountId, rows, lockouts, balance)
        : emptyComplianceSummary(),
    };
  }, [accountId, trades, lockouts, balance, failed]);
}
