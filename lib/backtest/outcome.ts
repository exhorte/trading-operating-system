/**
 * Trade outcome simulation for backtests (Phase 11). Pure — imports only
 * lib/domain.
 *
 * Honesty rules (MVP limits, surfaced in the UI):
 * - no spread/slippage/commissions: fills are at the exact level;
 * - binary exits: first bar whose range touches SL or TP decides;
 * - if ONE bar touches BOTH levels, the CONSERVATIVE rule applies: stop
 *   first (loss), and the trade is flagged `bothTouch` so the rate of such
 *   ambiguous bars is visible in the results;
 * - no exit within `maxBars` → timeout, exit at that bar's close.
 * Results grade signal quality (R distribution) — not account performance.
 */

import type { Candle } from "@/lib/domain/market";
import type { Side } from "@/lib/domain/primitives";

export type TradeOutcome = "win" | "loss" | "timeout";

export interface SimulatedTrade {
  outcome: TradeOutcome;
  /** Result as a multiple of the initial risk (|entry − stop|). */
  rMultiple: number;
  /** Bars from entry (exclusive) to exit (inclusive). */
  barsHeld: number;
  exitPrice: number;
  /** The deciding bar touched both SL and TP (conservative loss applied). */
  bothTouch: boolean;
}

export function simulateTradeOutcome(args: {
  side: Side;
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
  /** Bars strictly AFTER the signal bar, chronological. */
  futureCandles: Candle[];
  maxBars: number;
}): SimulatedTrade | null {
  const { side, entryPrice, stopLoss, takeProfit, futureCandles, maxBars } = args;
  const risk = Math.abs(entryPrice - stopLoss);
  if (risk <= 0 || futureCandles.length === 0) {
    return null;
  }
  const direction = side === "buy" ? 1 : -1;
  const rewardR = (Math.abs(takeProfit - entryPrice)) / risk;

  const horizon = Math.min(maxBars, futureCandles.length);
  for (let i = 0; i < horizon; i += 1) {
    const bar = futureCandles[i];
    const hitStop = side === "buy" ? bar.low <= stopLoss : bar.high >= stopLoss;
    const hitTarget = side === "buy" ? bar.high >= takeProfit : bar.low <= takeProfit;

    if (hitStop) {
      // Conservative: a both-touch bar counts as a loss.
      return {
        outcome: "loss",
        rMultiple: -1,
        barsHeld: i + 1,
        exitPrice: stopLoss,
        bothTouch: hitTarget,
      };
    }
    if (hitTarget) {
      return {
        outcome: "win",
        rMultiple: rewardR,
        barsHeld: i + 1,
        exitPrice: takeProfit,
        bothTouch: false,
      };
    }
  }

  const lastBar = futureCandles[horizon - 1];
  const move = (lastBar.close - entryPrice) * direction;
  return {
    outcome: "timeout",
    rMultiple: Math.round((move / risk) * 100) / 100,
    barsHeld: horizon,
    exitPrice: lastBar.close,
    bothTouch: false,
  };
}
