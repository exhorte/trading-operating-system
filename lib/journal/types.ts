/**
 * The shape of one row from GET /api/journal/trades
 * (JournalRepository.GetTradesAsync).
 *
 * Canonical declaration. It was written out a third time when the account
 * analysis screen arrived (2026-09-20) — `/journal`'s page and T08's stats
 * module each had their own copy. T08 now imports this one; `/journal`'s
 * local copy is deliberately left in place for now (that page also fetches
 * setup proposals and carries its own error surface — migrating it is a
 * separate, riskier change than the type alone).
 */
export interface JournalTrade {
  brokerPositionId: string;
  symbol: string;
  side: string;
  volume: number;
  entryPrice: number | null;
  exitPrice: number;
  realizedPnl: number;
  stopLoss: number | null;
  /** Null when no position_opens row matched — duration is unknowable then. */
  openedAt: string | null;
  closedAt: string;
  hasCapture: boolean;
}
