/**
 * Iteration-1 entry trigger (Phase 12 Part B). Pure; imports only lib/domain
 * and lib/analysis (ATR). The experimental treatment arm — a real ICT setup —
 * to be compared against the periodic sampler (lib/mock/signals) as control.
 *
 * The setup, at the current (last) bar of `window`:
 *   1. directional bias (neutral never trades); side follows bias;
 *   2. a fresh aligned structure shift (within maxShiftAgeBars);
 *   3. a fresh aligned FVG formed AFTER the shift (within maxSetupAgeBars);
 *   4. the current bar is the FIRST to retest that FVG's zone;
 *   5. the current bar is a confirmation close (see ConfirmationClose);
 *   6. one signal per setup — implied by (4): only one bar can be the first
 *      touch, so no dedup state is needed;
 *   7. setup expiry — the age caps in (2)/(3).
 *
 * STATELESS BY CONSTRUCTION. "First retest" and "one per setup" are derived
 * from the window, never tracked. This is deliberate: `fvgId` is a rolling-
 * window index (see lib/analysis/pd-arrays), not stable across bars, so any
 * state keyed by it would corrupt. Reading only the window also makes the
 * no-look-ahead invariant trivial — the signal at bar i cannot see bar i+1.
 *
 * The MarketContextState cannot answer "first retest": activeFairValueGaps only
 * drops 100%-filled gaps and filledPercent runs to the last candle, so a gap
 * touched at i looks identical to one touched at i-5. Hence the window scan here.
 */

import { averageTrueRange } from "@/lib/analysis/atr";
import type { FairValueGap, MarketContextState } from "@/lib/domain/analysis";
import type { Candle } from "@/lib/domain/market";
import type { AccountId, Side } from "@/lib/domain/primitives";
import type { StrategySignal } from "@/lib/domain/strategy";
import { DEFAULT_TRIGGER_CONFIG, type TriggerConfig } from "./config";

export interface TriggerInput {
  /** Rolling window, oldest-first; the LAST element is the evaluation bar. */
  window: Candle[];
  /** Context computed by analyzeMarketContext on the SAME window. */
  context: MarketContextState;
  accountId: AccountId;
  /** Symbol tick size, for the stop-buffer floor. */
  tickSize: number;
  seq: number;
  /** Session-unique id prefix so signal ids never collide across runs/tabs. */
  runId?: string;
  config?: TriggerConfig;
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/** A candle overlaps a price zone (a "touch"). */
function touches(candle: Candle, low: number, high: number): boolean {
  return candle.low <= high && candle.high >= low;
}

function isConfirmation(
  candle: Candle,
  side: Side,
  fvg: FairValueGap,
  mode: TriggerConfig["confirmationClose"],
): boolean {
  const inDirection = side === "buy" ? candle.close > candle.open : candle.close < candle.open;
  if (mode === "lenient") {
    return inDirection;
  }
  if (mode === "strict") {
    // Closed fully beyond the gap (strongest rejection of the retest).
    return inDirection && (side === "buy" ? candle.close > fvg.high : candle.close < fvg.low);
  }
  // middle: in direction AND the gap held (didn't close through its far edge).
  return inDirection && (side === "buy" ? candle.close > fvg.low : candle.close < fvg.high);
}

/**
 * Evaluate the trigger at the last bar of the window. Returns a StrategySignal
 * when the full setup is present, otherwise null.
 */
export function evaluateTrigger(input: TriggerInput): StrategySignal | null {
  const cfg = input.config ?? DEFAULT_TRIGGER_CONFIG;
  const { window, context, tickSize } = input;
  if (window.length < 3) {
    return null;
  }

  const currentIndex = window.length - 1;
  const bar = window[currentIndex];

  // 1. Directional bias.
  if (context.bias !== "bullish" && context.bias !== "bearish") {
    return null;
  }
  const side: Side = context.bias === "bullish" ? "buy" : "sell";

  // 2. Fresh aligned structure shift.
  const shift = context.lastStructureShift;
  if (!shift || shift.direction !== context.bias) {
    return null;
  }
  const indexByTime = new Map(window.map((c, i) => [c.openTime, i]));
  const shiftIndex = indexByTime.get(shift.occurredAt);
  if (shiftIndex === undefined || currentIndex - shiftIndex > cfg.maxShiftAgeBars) {
    return null;
  }

  // 3. Fresh aligned FVG formed AFTER the shift. Among candidates, the most
  //    recent one is the displacement's gap; older-than-cap means expired.
  const candidates = context.activeFairValueGaps
    .filter((g) => g.direction === context.bias)
    .map((g) => ({ g, i: indexByTime.get(g.detectedAt) }))
    .filter((x): x is { g: FairValueGap; i: number } => x.i !== undefined && x.i > shiftIndex)
    .sort((a, b) => b.i - a.i);
  const fresh = candidates.find(({ i }) => currentIndex - i <= cfg.maxSetupAgeBars);
  if (!fresh) {
    return null;
  }
  const { g: fvg, i: fvgIndex } = fresh;

  // 4. First retest: no bar between formation and now has touched the zone,
  //    and the current bar does.
  for (let t = fvgIndex + 1; t < currentIndex; t += 1) {
    if (touches(window[t], fvg.low, fvg.high)) {
      return null; // an earlier bar already retested — this is not the first
    }
  }
  if (!touches(bar, fvg.low, fvg.high)) {
    return null;
  }

  // 5. Confirmation close on this first-retest bar.
  if (!isConfirmation(bar, side, fvg, cfg.confirmationClose)) {
    return null;
  }

  // 6/7. One-per-setup and expiry are already guaranteed by (4) and the caps.

  // Levels: stop beyond the FVG's far edge + ATR buffer (floored at ticks);
  // target at the fixed reward multiple. Entry is the confirmed close.
  const atr = averageTrueRange(window, cfg.atrPeriod);
  const buffer = Math.max(atr * cfg.atrBufferMultiple, cfg.minStopTicks * tickSize);
  const entry = bar.close;
  const stopLoss = side === "buy" ? fvg.low - buffer : fvg.high + buffer;
  const risk = Math.abs(entry - stopLoss);
  const takeProfit = side === "buy" ? entry + cfg.rewardMultiple * risk : entry - cfg.rewardMultiple * risk;

  const now = bar.openTime;
  return {
    signalId: input.runId ? `sig-${input.runId}-${input.seq}` : `sig-${String(input.seq).padStart(3, "0")}`,
    strategyId: "ict-fvg-retest-v1",
    accountId: input.accountId,
    symbol: context.symbol,
    side,
    status: "risk_review",
    entryPrice: round2(entry),
    stopLoss: round2(stopLoss),
    takeProfit: round2(takeProfit),
    score: context.score,
    maxScore: context.maxScore,
    marketContext: context,
    riskApprovalId: null,
    createdAt: now,
    expiresAt: new Date(new Date(now).getTime() + 5 * 60_000).toISOString(),
  };
}
