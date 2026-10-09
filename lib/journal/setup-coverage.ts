import { STRATEGY_MAX_LOOKBACK_DAYS } from "@/lib/api/generated";

const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;

/**
 * What the S01 context of the journal rests on: the proposals S01 made and the matching of trades to them (`strategy_proposals`,
 * `strategy_agreement`). It is an enrichment of the journal — the trades never wait for it — so it has three states, and the dark
 * panel draws a dash, never a zero, for the two that are not an answer.
 */
export type SetupContext =
  | { status: "loading" }
  | { status: "unavailable" }
  | { status: "ready"; since: string; truncated: boolean };

export interface SetupCoverage {
  /** The `since` to ask the strategy reads for: the start of the period, or the earliest instant the core answers for. */
  since: string;
  /** The period starts further back than the core answers for: the S01 figures then describe only the end of it. */
  truncated: boolean;
}

/**
 * The core refuses a strategy read that reaches more than `STRATEGY_MAX_LOOKBACK_DAYS` back (a 422), and the journal's period is
 * the trader's to choose (90 days by default). The context is therefore asked for from the period's start or from the earliest
 * instant the core will answer for, whichever is later — and the screen says when that is less than the period.
 *
 * The earliest instant sits one day inside the cap, because the core judges the cap on its own clock when the request arrives,
 * and is rounded down to the hour: it is part of the question asked, and a question that changed at every render would be asked
 * again at every render.
 */
export function setupCoverage(periodStart: string, now: number): SetupCoverage {
  const earliest = Math.floor((now - (STRATEGY_MAX_LOOKBACK_DAYS - 1) * DAY_MS) / HOUR_MS) * HOUR_MS;
  const start = Date.parse(periodStart);
  if (Number.isNaN(start) || start >= earliest) {
    return { since: periodStart, truncated: false };
  }
  return { since: new Date(earliest).toISOString(), truncated: true };
}

export interface CoverableTrade {
  openedAt: string | null;
  closedAt: string;
  /** The core matched a proposal of S01 to this trade. */
  proposed: boolean;
}

/**
 * How many of the trades S01 can speak about coincided with a proposal. A trade is covered when it opened inside the span the
 * context was read for — the core matches by opening time, and a trade opened before `since` could have coincided with a proposal
 * that was never asked for, so it is neither counted as taken on one nor as taken without. `null` when there is no context, or
 * when it covers no trade: a dash, not « 0 / 0 ».
 */
export function setupShare(
  trades: readonly CoverableTrade[],
  context: SetupContext,
): { proposed: number; of: number } | null {
  if (context.status !== "ready") {
    return null;
  }
  const since = Date.parse(context.since);
  const covered = trades.filter((trade) => Date.parse(trade.openedAt ?? trade.closedAt) >= since);
  if (covered.length === 0) {
    return null;
  }
  return { proposed: covered.filter((trade) => trade.proposed).length, of: covered.length };
}
