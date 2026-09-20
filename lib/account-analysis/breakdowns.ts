/**
 * Account analysis — pure aggregation over closed trades.
 *
 * The dimensions the FTMO "Analyse de compte" report breaks results down by
 * and `/journal` does not: trade duration, position size, opening *and*
 * closing day as two separate readings, buy vs sell, and the shape of a
 * trading day. Kept pure and separate from both fetching and rendering, the
 * same way T08 split `stats.ts` from `render.ts` — so every number can be
 * checked against the database by hand.
 *
 * No performance verdict is computed here, and none should be: these are
 * descriptions of what happened, on a sample far too small to support a
 * claim about an edge (ADR 0002). `lib/compliance/` remains the only place
 * that judges anything.
 */

import type { JournalTrade } from "@/lib/journal/types";

export interface Bucket {
  label: string;
  trades: number;
  pnl: number;
}

/**
 * Aggregates by a key derived per trade. A null key drops the trade rather
 * than pooling it under a fake "unknown" bucket whose P&L total would
 * silently absorb it — same rule as `/journal`'s own `bucketBy`, restated
 * here because this module must not import from a page.
 */
export function bucketBy(
  trades: JournalTrade[],
  keyOf: (trade: JournalTrade) => string | null,
): Bucket[] {
  const byLabel = new Map<string, Bucket>();
  for (const trade of trades) {
    const label = keyOf(trade);
    if (label === null) {
      continue;
    }
    const existing = byLabel.get(label);
    if (existing) {
      existing.trades += 1;
      existing.pnl += trade.realizedPnl;
    } else {
      byLabel.set(label, { label, trades: 1, pnl: trade.realizedPnl });
    }
  }
  return [...byLabel.values()];
}

/** Ordered so a breakdown table reads chronologically, not by frequency. */
const DURATION_BUCKETS: Array<{ label: string; maxSeconds: number }> = [
  { label: "< 2 min", maxSeconds: 120 },
  { label: "2 – 5 min", maxSeconds: 300 },
  { label: "5 – 15 min", maxSeconds: 900 },
  { label: "15 – 60 min", maxSeconds: 3600 },
  { label: "> 1 h", maxSeconds: Number.POSITIVE_INFINITY },
];

const WEEKDAY_LABELS = ["Dimanche", "Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"];

/** Seconds a position was open, or null when it has no recorded opening. */
export function durationSeconds(trade: JournalTrade): number | null {
  if (trade.openedAt === null) {
    return null;
  }
  const ms = Date.parse(trade.closedAt) - Date.parse(trade.openedAt);
  return ms < 0 ? null : Math.round(ms / 1000);
}

export function durationLabel(trade: JournalTrade): string | null {
  const seconds = durationSeconds(trade);
  if (seconds === null) {
    return null;
  }
  return DURATION_BUCKETS.find((b) => seconds < b.maxSeconds)?.label ?? "> 1 h";
}

/** Re-sorts a duration breakdown into the buckets' own order. */
function sortByDuration(buckets: Bucket[]): Bucket[] {
  const order = DURATION_BUCKETS.map((b) => b.label);
  return [...buckets].sort((a, b) => order.indexOf(a.label) - order.indexOf(b.label));
}

function sortByWeekday(buckets: Bucket[]): Bucket[] {
  // Monday first: a trading week does not start on Sunday.
  const order = [...WEEKDAY_LABELS.slice(1), WEEKDAY_LABELS[0]];
  return [...buckets].sort((a, b) => order.indexOf(a.label) - order.indexOf(b.label));
}

export interface GeneralStats {
  tradeCount: number;
  netPnl: number;
  /** Trades closed above zero, as a share of all trades (0..1). */
  winRate: number;
  wins: number;
  losses: number;
  /** Trades closed exactly flat — counted in neither average. */
  breakeven: number;
  /** Mean P&L of winning trades, or null when there were none. */
  avgWin: number | null;
  /** Mean P&L of losing trades (negative), or null when there were none. */
  avgLoss: number | null;
  maxWin: number | null;
  maxLoss: number | null;
  /**
   * Average win over average loss, FTMO's "RRR". Null when either side is
   * missing — a ratio computed against zero losing trades is not a high
   * ratio, it is an unknown one.
   */
  rewardRiskRatio: number | null;
}

export function generalStats(trades: JournalTrade[]): GeneralStats {
  const wins = trades.filter((t) => t.realizedPnl > 0);
  const losses = trades.filter((t) => t.realizedPnl < 0);
  const breakeven = trades.length - wins.length - losses.length;

  const avgWin = wins.length > 0 ? wins.reduce((s, t) => s + t.realizedPnl, 0) / wins.length : null;
  const avgLoss =
    losses.length > 0 ? losses.reduce((s, t) => s + t.realizedPnl, 0) / losses.length : null;

  return {
    tradeCount: trades.length,
    netPnl: trades.reduce((sum, t) => sum + t.realizedPnl, 0),
    winRate: trades.length > 0 ? wins.length / trades.length : 0,
    wins: wins.length,
    losses: losses.length,
    breakeven,
    avgWin,
    avgLoss,
    maxWin: wins.length > 0 ? Math.max(...wins.map((t) => t.realizedPnl)) : null,
    maxLoss: losses.length > 0 ? Math.min(...losses.map((t) => t.realizedPnl)) : null,
    rewardRiskRatio:
      avgWin !== null && avgLoss !== null && avgLoss !== 0 ? avgWin / Math.abs(avgLoss) : null,
  };
}

export interface TradingDayStats {
  /** Distinct UTC dates on which at least one trade was closed. */
  dayCount: number;
  avgTradesPerDay: number | null;
  positiveDays: number;
  negativeDays: number;
  flatDays: number;
  avgPositiveDay: number | null;
  avgNegativeDay: number | null;
  bestDay: Bucket | null;
  worstDay: Bucket | null;
}

/**
 * The shape of a trading day, keyed on the closing date — the reading FTMO
 * uses for its "Analyse jours de trading" block, and the one that matches a
 * daily-loss limit, which resets on the day a loss is realised.
 */
export function tradingDayStats(trades: JournalTrade[]): TradingDayStats {
  const days = bucketBy(trades, (t) => t.closedAt.slice(0, 10));
  const positive = days.filter((d) => d.pnl > 0);
  const negative = days.filter((d) => d.pnl < 0);

  const mean = (list: Bucket[]) =>
    list.length > 0 ? list.reduce((s, d) => s + d.pnl, 0) / list.length : null;

  return {
    dayCount: days.length,
    avgTradesPerDay: days.length > 0 ? trades.length / days.length : null,
    positiveDays: positive.length,
    negativeDays: negative.length,
    flatDays: days.length - positive.length - negative.length,
    avgPositiveDay: mean(positive),
    avgNegativeDay: mean(negative),
    bestDay: days.length > 0 ? days.reduce((b, d) => (d.pnl > b.pnl ? d : b)) : null,
    worstDay: days.length > 0 ? days.reduce((w, d) => (d.pnl < w.pnl ? d : w)) : null,
  };
}

export interface AccountBreakdowns {
  byDuration: Bucket[];
  bySize: Bucket[];
  byOpenDay: Bucket[];
  byCloseDay: Bucket[];
  byOpenHour: Bucket[];
  bySide: Bucket[];
  bySymbol: Bucket[];
}

/**
 * `byOpenDay` and `byCloseDay` are deliberately two readings of the same
 * trades: a position opened Monday and closed Tuesday belongs to a
 * different day depending on the question asked, and collapsing them into
 * one column is what makes a "bad Monday" impossible to locate. FTMO shows
 * both side by side for the same reason.
 *
 * Hours are UTC, and labelled as such by the screen — an hour breakdown
 * whose timezone is left implicit is a breakdown nobody can act on.
 */
export function accountBreakdowns(trades: JournalTrade[]): AccountBreakdowns {
  return {
    byDuration: sortByDuration(bucketBy(trades, durationLabel)),
    bySize: bucketBy(trades, (t) => t.volume.toFixed(2)).sort(
      (a, b) => Number(a.label) - Number(b.label),
    ),
    byOpenDay: sortByWeekday(
      bucketBy(trades, (t) =>
        t.openedAt ? WEEKDAY_LABELS[new Date(t.openedAt).getUTCDay()] : null,
      ),
    ),
    byCloseDay: sortByWeekday(
      bucketBy(trades, (t) => WEEKDAY_LABELS[new Date(t.closedAt).getUTCDay()]),
    ),
    byOpenHour: bucketBy(trades, (t) =>
      t.openedAt ? `${String(new Date(t.openedAt).getUTCHours()).padStart(2, "0")}:00` : null,
    ).sort((a, b) => a.label.localeCompare(b.label)),
    bySide: bucketBy(trades, (t) => (t.side === "buy" ? "Achat" : "Vente")),
    bySymbol: bucketBy(trades, (t) => t.symbol).sort((a, b) => b.trades - a.trades),
  };
}

/** The bucket holding the most trades — what the narrative leads with. */
export function mostFrequent(buckets: Bucket[]): Bucket | null {
  if (buckets.length === 0) {
    return null;
  }
  return buckets.reduce((most, b) => (b.trades > most.trades ? b : most));
}

/** The bucket with the worst P&L, or null when nothing lost money. */
export function worstBucket(buckets: Bucket[]): Bucket | null {
  const losing = buckets.filter((b) => b.pnl < 0);
  if (losing.length === 0) {
    return null;
  }
  return losing.reduce((worst, b) => (b.pnl < worst.pnl ? b : worst));
}
