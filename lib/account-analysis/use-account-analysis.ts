"use client";

import { useMemo } from "react";
import type { JournalTradeView, ViolationType } from "@/lib/api/generated";
import { useCockpit } from "@/lib/realtime/provider";
import { useJournalWindow } from "@/lib/journal/use-journal-window";
import {
  accountBreakdowns,
  generalStats,
  tradingDayStats,
  type AccountBreakdowns,
  type GeneralStats,
  type TradingDayStats,
} from "./breakdowns";

/** The compliance figures the screen draws — the core's verdict over the window, counted and never recomputed. */
export interface AnalysisCompliance {
  /** 0..1, or null while the core has not answered. */
  rate: number | null;
  tradeCount: number;
  /** Trades carrying at least one violation. */
  breachedCount: number;
  /** Occurrences per violation type — every type is present, zero included. */
  byType: Record<ViolationType, number>;
}

export interface AccountAnalysis {
  loading: boolean;
  failed: boolean;
  /** Empty while loading — check `loading` before reading anything else. */
  trades: JournalTradeView[];
  general: GeneralStats;
  tradingDays: TradingDayStats;
  breakdowns: AccountBreakdowns;
  compliance: AnalysisCompliance;
}

const NO_VIOLATIONS: Record<ViolationType, number> = { LOCKOUT_ACTIVE: 0, SESSION_WINDOW: 0, SIZE_POLICY: 0 };

/**
 * Everything `/analyse` shows, for one date range.
 *
 * Its own read, over the range the trader picked — unlike `useComplianceRate`, whose window is a fixed trailing 7 days on
 * purpose so the figure means the same thing everywhere. The trades and the verdict on them are the core's; the groupings
 * and the sentences over them (`breakdowns`, `narrative`) are presentation, and stay here.
 */
export function useAccountAnalysis(fromDate: string, toDate: string): AccountAnalysis {
  const { activeAccountId: accountId } = useCockpit();

  const { trades, compliance, failed } = useJournalWindow(accountId, fromDate, toDate, {
    trades: true,
    compliance: true,
  });

  return useMemo(() => {
    const rows = trades ?? [];
    return {
      loading: accountId !== null && (trades === null || compliance === null) && !failed,
      failed,
      trades: rows,
      general: generalStats(rows),
      tradingDays: tradingDayStats(rows),
      breakdowns: accountBreakdowns(rows),
      compliance: {
        rate: compliance === null ? null : compliance.rate,
        tradeCount: compliance?.tradeCount ?? 0,
        breachedCount: compliance?.breachedCount ?? 0,
        byType: { ...NO_VIOLATIONS, ...(compliance?.byType as Partial<Record<ViolationType, number>> | undefined) },
      },
    };
  }, [accountId, trades, compliance, failed]);
}
