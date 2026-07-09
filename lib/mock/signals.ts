/**
 * Mock strategy: turn the computed MarketContextState into a domain
 * StrategySignal (side from bias, fixed-distance stop/target). Deliberately
 * simple — it exists to exercise the real Signal → Risk Review flow, not to be
 * a validated strategy. The signal carries its frozen market context for
 * explainability; the risk engine rules on it downstream.
 */

import type { MarketContextState } from "@/lib/domain/analysis";
import type { Side } from "@/lib/domain/primitives";
import type { StrategySignal } from "@/lib/domain/strategy";
import type { AccountSummary } from "@/lib/contracts/snapshots";

/** XAUUSD fixed stop distance (price units) for the mock. */
const STOP_DISTANCE = 5.0;

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

export function mockStrategySignal(args: {
  context: MarketContextState;
  account: AccountSummary;
  price: number;
  seq: number;
}): StrategySignal {
  const { context, account, price, seq } = args;
  const side: Side = context.bias === "bearish" ? "sell" : "buy";
  const stopLoss = side === "buy" ? price - STOP_DISTANCE : price + STOP_DISTANCE;
  const takeProfit = side === "buy" ? price + 2 * STOP_DISTANCE : price - 2 * STOP_DISTANCE;
  const now = new Date();

  return {
    signalId: `sig-${String(seq).padStart(3, "0")}`,
    strategyId: side === "buy" ? "ict-silver-bullet-v1" : "ict-fvg-continuation-v1",
    accountId: account.accountId,
    symbol: context.symbol,
    side,
    status: "risk_review",
    entryPrice: round2(price),
    stopLoss: round2(stopLoss),
    takeProfit: round2(takeProfit),
    score: context.score,
    maxScore: context.maxScore,
    marketContext: context,
    riskApprovalId: null,
    createdAt: now.toISOString(),
    expiresAt: new Date(now.getTime() + 5 * 60_000).toISOString(),
  };
}
