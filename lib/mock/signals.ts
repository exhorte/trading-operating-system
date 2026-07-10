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

  // Variety: every 4th signal is a counter-bias probe with a weaker score, so
  // the queue shows both sides; stop distance cycles 3.5→8.0 so the risk
  // engine sizes different volumes per signal.
  const counterBias = seq % 4 === 0;
  const withBias: Side = context.bias === "bearish" ? "sell" : "buy";
  const side: Side = counterBias ? (withBias === "buy" ? "sell" : "buy") : withBias;
  const score = counterBias ? Math.max(2, context.score - 3) : context.score;
  const stopDistance = 3.5 + (seq % 4) * 1.5;

  const stopLoss = side === "buy" ? price - stopDistance : price + stopDistance;
  const takeProfit = side === "buy" ? price + 2 * stopDistance : price - 2 * stopDistance;
  const now = new Date();

  return {
    signalId: `sig-${String(seq).padStart(3, "0")}`,
    strategyId: counterBias
      ? "ict-liquidity-raid-v1"
      : side === "buy"
        ? "ict-silver-bullet-v1"
        : "ict-fvg-continuation-v1",
    accountId: account.accountId,
    symbol: context.symbol,
    side,
    status: "risk_review",
    entryPrice: round2(price),
    stopLoss: round2(stopLoss),
    takeProfit: round2(takeProfit),
    score,
    maxScore: context.maxScore,
    marketContext: context,
    riskApprovalId: null,
    createdAt: now.toISOString(),
    expiresAt: new Date(now.getTime() + 5 * 60_000).toISOString(),
  };
}
