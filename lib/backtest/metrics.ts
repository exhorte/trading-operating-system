/**
 * Aggregate metrics over simulated backtest trades (Phase 11). Pure.
 * Everything here grades a HYPOTHESIS (tagged engine version), never a
 * validated edge.
 */

import type { SimulatedTrade } from "./outcome";

export interface BacktestMetrics {
  tradeCount: number;
  winCount: number;
  lossCount: number;
  timeoutCount: number;
  bothTouchCount: number;
  /** Wins over decided trades (win+loss), 0-100. Timeouts excluded. */
  winRate: number;
  /** Mean R over DECIDED trades only (win+loss). */
  avgR: number;
  /** Mean R per trade including timeouts — the expectancy of taking a signal. */
  expectancyR: number;
  maxConsecutiveLosses: number;
  cumulativeR: number;
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

export function computeMetrics(trades: SimulatedTrade[]): BacktestMetrics {
  const wins = trades.filter((t) => t.outcome === "win").length;
  const losses = trades.filter((t) => t.outcome === "loss").length;
  const timeouts = trades.filter((t) => t.outcome === "timeout").length;
  const decided = wins + losses;
  const totalR = trades.reduce((sum, t) => sum + t.rMultiple, 0);
  const decidedR = trades
    .filter((t) => t.outcome !== "timeout")
    .reduce((sum, t) => sum + t.rMultiple, 0);

  let consec = 0;
  let maxConsec = 0;
  for (const trade of trades) {
    if (trade.outcome === "loss" || (trade.outcome === "timeout" && trade.rMultiple < 0)) {
      consec += 1;
      maxConsec = Math.max(maxConsec, consec);
    } else {
      consec = 0;
    }
  }

  return {
    tradeCount: trades.length,
    winCount: wins,
    lossCount: losses,
    timeoutCount: timeouts,
    bothTouchCount: trades.filter((t) => t.bothTouch).length,
    winRate: decided > 0 ? round2((wins / decided) * 100) : 0,
    avgR: decided > 0 ? round2(decidedR / decided) : 0,
    expectancyR: trades.length > 0 ? round2(totalR / trades.length) : 0,
    maxConsecutiveLosses: maxConsec,
    cumulativeR: round2(totalR),
  };
}
