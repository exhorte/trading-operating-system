/**
 * EA-02 — reconciliation between what the machine proposed and what was
 * actually traded (S01, "Critère de réussite"; ADR 0011: agreement, never
 * performance). Pure: takes plain arrays, no DB, no HTTP.
 */

import type { Side, UtcTimestamp } from "@/lib/domain/primitives";

export type ReconciliationClass = "PROPOSE_ET_PRIS" | "PROPOSE_ET_REFUSE" | "PRIS_SANS_PROPOSITION";

export interface ReconciliationProposal {
  symbol: string;
  side: Side;
  detectedAt: UtcTimestamp;
}

export interface ReconciliationTrade {
  brokerPositionId: string;
  symbol: string;
  side: Side;
  openedAt: UtcTimestamp;
}

export interface ReconciliationRow {
  class: ReconciliationClass;
  symbol: string;
  side: Side;
  proposalDetectedAt: UtcTimestamp | null;
  tradeOpenedAt: UtcTimestamp | null;
  brokerPositionId: string | null;
}

/**
 * Matches proposals to trades on the same symbol and side within
 * `toleranceMinutes` of the proposal's detection time — "un trade pris
 * trois minutes après une proposition sur le même niveau est le même
 * trade" (EA-02 prompt). Matching is GLOBALLY nearest-first (every valid
 * pair is ranked by time distance and claimed in that order), not
 * first-proposal-first: with two proposals a minute apart and one trade
 * between them, the trade must go to whichever proposal it's actually
 * closer to, not to whichever proposal happens to come first in the array.
 * Each trade matches at most one proposal, and vice versa. An unmatched
 * proposal is PROPOSE_ET_REFUSE; an unmatched trade is
 * PRIS_SANS_PROPOSITION — the class the fiche calls the most important one.
 */
export function reconcile(
  proposals: ReconciliationProposal[],
  trades: ReconciliationTrade[],
  toleranceMinutes: number,
): ReconciliationRow[] {
  const toleranceMs = toleranceMinutes * 60_000;

  const candidatePairs: { proposalIndex: number; trade: ReconciliationTrade; distanceMs: number }[] = [];
  proposals.forEach((proposal, proposalIndex) => {
    const detectedAtMs = Date.parse(proposal.detectedAt);
    for (const trade of trades) {
      if (trade.symbol !== proposal.symbol || trade.side !== proposal.side) {
        continue;
      }
      const distanceMs = Math.abs(Date.parse(trade.openedAt) - detectedAtMs);
      if (distanceMs <= toleranceMs) {
        candidatePairs.push({ proposalIndex, trade, distanceMs });
      }
    }
  });
  candidatePairs.sort((a, b) => a.distanceMs - b.distanceMs);

  const matchByProposalIndex = new Map<number, ReconciliationTrade>();
  const matchedTradeIds = new Set<string>();
  for (const pair of candidatePairs) {
    if (matchByProposalIndex.has(pair.proposalIndex) || matchedTradeIds.has(pair.trade.brokerPositionId)) {
      continue;
    }
    matchByProposalIndex.set(pair.proposalIndex, pair.trade);
    matchedTradeIds.add(pair.trade.brokerPositionId);
  }

  const rows: ReconciliationRow[] = proposals.map((proposal, proposalIndex) => {
    const match = matchByProposalIndex.get(proposalIndex);
    return match
      ? {
          class: "PROPOSE_ET_PRIS" as const,
          symbol: proposal.symbol,
          side: proposal.side,
          proposalDetectedAt: proposal.detectedAt,
          tradeOpenedAt: match.openedAt,
          brokerPositionId: match.brokerPositionId,
        }
      : {
          class: "PROPOSE_ET_REFUSE" as const,
          symbol: proposal.symbol,
          side: proposal.side,
          proposalDetectedAt: proposal.detectedAt,
          tradeOpenedAt: null,
          brokerPositionId: null,
        };
  });

  for (const trade of trades) {
    if (!matchedTradeIds.has(trade.brokerPositionId)) {
      rows.push({
        class: "PRIS_SANS_PROPOSITION",
        symbol: trade.symbol,
        side: trade.side,
        proposalDetectedAt: null,
        tradeOpenedAt: trade.openedAt,
        brokerPositionId: trade.brokerPositionId,
      });
    }
  }

  return rows;
}
