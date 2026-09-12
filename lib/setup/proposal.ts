/**
 * S01 step 9 — assembles steps 1-8 into a SetupProposal, or null at the
 * first step that doesn't hold. Pre-conditions (session window, NY lunch,
 * calendar, lockouts — S01 "Pré-conditions") are NOT evaluated here: they
 * are consumed from T02a/T02b/T03 when this is wired live in EA-02, never
 * duplicated (S01, "Ancrage dans le code").
 */

import type { Candle, SessionWindow } from "@/lib/domain/market";
import type { Side } from "@/lib/domain/primitives";
import type { SetupProposal } from "@/lib/domain/setup";
import type { Swing } from "@/lib/analysis/types";
import { detectSwings } from "@/lib/analysis/swings";
import { detectStructureShifts } from "@/lib/analysis/structure";
import { detectOrderBlocks } from "@/lib/analysis/pd-arrays";
import { dailyBias } from "./bias";
import { lastDealingRange, locationInRange } from "./dealing-range";
import { liquidityPool, opposingTarget, sweepTriggerCandidate } from "./liquidity";
import { detectSweep } from "./sweep";
import { detectDisplacement } from "./displacement";
import { pointOfInterestFor } from "./poi";
import { computeStopLoss } from "./stop";
import { evaluateViabilityGates } from "./gates";

export interface SetupProposalInput {
  symbol: string;
  h4Candles: Candle[];
  d1Candles: Candle[];
  h1Candles: Candle[];
  /**
   * Entry-timeframe (M1) candles BEFORE the reaction window — maps
   * liquidity and the swing structure a displacement must break. Must NOT
   * include the candle(s) that perform the sweep: detectLiquidity's
   * sweptAt scans forward through whatever series it's given, so a pool
   * computed over candles that already contain the sweep would see the
   * level as "already swept" and reject the very trigger this pipeline is
   * trying to identify. The split mirrors how this runs live (EA-02): the
   * pool is what's known *before* watching for a sweep, not a replay of
   * the whole outcome at once.
   */
  contextCandles: Candle[];
  /** Entry-timeframe (M1) candles from the moment the sweep is watched for, through the displacement. */
  reactionCandles: Candle[];
  swingLookback: number;
  equalLevelTolerance: number;
  sessionWindows: SessionWindow[];
  atrPeriod: number;
  minBodyAtrMultiple: number;
  minFvgSize: number;
  spreadBuffer: number;
  /** Live spread and commission, price units — see lib/setup/gates.ts. */
  spread: number;
  commission: number;
  costThreshold: number;
  minRiskReward: number;
  maxStopDistance?: number;
}

/** Most recent context swing of the kind a displacement in `side`'s
 * direction must break (a buy breaks the last swing high, a sell the last
 * swing low). */
function lastOppositeSwing(swings: Swing[], side: Side): Swing | null {
  const wantKind = side === "buy" ? "high" : "low";
  const candidates = swings.filter((s) => s.kind === wantKind);
  if (candidates.length === 0) {
    return null;
  }
  return candidates.reduce((a, b) => (a.index > b.index ? a : b));
}

export function proposeSetup(input: SetupProposalInput): SetupProposal | null {
  const bias = dailyBias(input.h4Candles, input.d1Candles, input.swingLookback);
  if (bias === "neutral") {
    return null;
  }
  const side: Side = bias === "bullish" ? "buy" : "sell";

  const range = lastDealingRange(input.h1Candles, input.swingLookback);
  if (!range) {
    return null;
  }
  const h1Last = input.h1Candles.at(-1);
  if (!h1Last) {
    return null;
  }
  const location = locationInRange(h1Last.close, range);
  if ((side === "buy" && location !== "discount") || (side === "sell" && location !== "premium")) {
    return null;
  }

  const contextSwings = detectSwings(input.contextCandles, input.swingLookback);
  const pool = liquidityPool(input.contextCandles, contextSwings, input.equalLevelTolerance, input.sessionWindows);
  const contextLast = input.contextCandles.at(-1);
  if (!contextLast) {
    return null;
  }
  const referencePrice = contextLast.close;

  const triggerLevel = sweepTriggerCandidate(pool, side, referencePrice);
  if (!triggerLevel) {
    return null;
  }
  const target = opposingTarget(pool, side, referencePrice);
  if (!target) {
    return null;
  }

  const sweep = detectSweep(input.reactionCandles, { kind: triggerLevel.kind, price: triggerLevel.price }, side);
  if (!sweep) {
    return null;
  }

  const oppositeSwing = lastOppositeSwing(contextSwings, side);
  if (!oppositeSwing) {
    return null;
  }

  const sweepIndex = input.reactionCandles.findIndex((c) => c.openTime === sweep.sweptAt);
  const postSweepCandles = input.reactionCandles.slice(sweepIndex + 1);
  const displacement = detectDisplacement(postSweepCandles, side, oppositeSwing.price, {
    atrPeriod: input.atrPeriod,
    minBodyAtrMultiple: input.minBodyAtrMultiple,
    minFvgSize: input.minFvgSize,
  });
  if (!displacement) {
    return null;
  }

  const allCandles = [...input.contextCandles, ...input.reactionCandles];
  const allSwings = detectSwings(allCandles, input.swingLookback);
  const structureShifts = detectStructureShifts(allCandles, allSwings, input.swingLookback);
  const orderBlocks = detectOrderBlocks(allCandles, structureShifts);
  const poi = pointOfInterestFor(displacement, orderBlocks, side);
  if (!poi) {
    return null;
  }

  const entryPrice = poi.ce;
  const stop = computeStopLoss(side, sweep.wickExtreme, input.spreadBuffer, entryPrice, input.maxStopDistance);
  if (!stop) {
    return null;
  }

  const gate = evaluateViabilityGates({
    entryPrice,
    stopDistance: stop.distance,
    targetPrice: target.price,
    side,
    spread: input.spread,
    commission: input.commission,
    costThreshold: input.costThreshold,
    minRiskReward: input.minRiskReward,
  });
  if (!gate.passed) {
    return null;
  }

  return {
    proposalId: `setup-${input.symbol}-${displacement.occurredAt}`,
    symbol: input.symbol,
    side,
    sweptLevelKind: triggerLevel.kind,
    sweptLevelPrice: triggerLevel.price,
    entryPrice,
    stopLoss: stop.price,
    takeProfit: target.price,
    costRatio: gate.costRatio,
    riskRewardRatio: gate.riskRewardRatio,
    detectedAt: displacement.occurredAt,
  };
}
