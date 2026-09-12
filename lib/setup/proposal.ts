/**
 * S01 step 9 — assembles steps 1-8 into a SetupProposal, or null at the
 * first step that doesn't hold. Pre-conditions (session window, NY lunch,
 * calendar, lockouts — S01 "Pré-conditions") are NOT evaluated here: they
 * are consumed from T02a/T02b/T03 when this is wired live in EA-02, never
 * duplicated (S01, "Ancrage dans le code").
 */

import type { Candle, SessionWindow } from "@/lib/domain/market";
import type { Side } from "@/lib/domain/primitives";
import type { SetupOutcome, SetupProposal } from "@/lib/domain/setup";
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

/**
 * The full step-by-step evaluation: either a completed proposal, or the
 * exact stage where the sequence stopped and why (EA-02 needs this to
 * measure agreement — "l'étape exacte... dit POURQUOI la machine n'a rien
 * proposé"). `proposeSetup` below is a thin wrapper for callers that only
 * care about the proposal itself (EA-01's original shape, unchanged).
 */
export function evaluateSetup(input: SetupProposalInput): SetupOutcome {
  const bias = dailyBias(input.h4Candles, input.d1Candles, input.swingLookback);
  if (bias === "neutral") {
    return { status: "blocked", stage: "bias", detail: "H4/D1 disagree or show no confirmed structure" };
  }
  const side: Side = bias === "bullish" ? "buy" : "sell";

  const range = lastDealingRange(input.h1Candles, input.swingLookback);
  if (!range) {
    return { status: "blocked", stage: "dealing_range", detail: "fewer than two 1H swings to anchor a range" };
  }
  const h1Last = input.h1Candles.at(-1);
  if (!h1Last) {
    return { status: "blocked", stage: "dealing_range", detail: "no 1H candles" };
  }
  const location = locationInRange(h1Last.close, range);
  if ((side === "buy" && location !== "discount") || (side === "sell" && location !== "premium")) {
    return {
      status: "blocked",
      stage: "range_location",
      detail: `price is ${location}, need ${side === "buy" ? "discount" : "premium"} for a ${side}`,
    };
  }

  const contextSwings = detectSwings(input.contextCandles, input.swingLookback);
  const pool = liquidityPool(input.contextCandles, contextSwings, input.equalLevelTolerance, input.sessionWindows);
  const contextLast = input.contextCandles.at(-1);
  if (!contextLast) {
    return { status: "blocked", stage: "liquidity", detail: "no context candles" };
  }
  const referencePrice = contextLast.close;

  const triggerLevel = sweepTriggerCandidate(pool, side, referencePrice);
  if (!triggerLevel) {
    return { status: "blocked", stage: "liquidity", detail: "no resting liquidity on the trigger side" };
  }
  const target = opposingTarget(pool, side, referencePrice);
  if (!target) {
    return { status: "blocked", stage: "liquidity", detail: "no unswept liquidity on the target side" };
  }

  const sweep = detectSweep(input.reactionCandles, { kind: triggerLevel.kind, price: triggerLevel.price }, side);
  if (!sweep) {
    return { status: "blocked", stage: "sweep", detail: "level never touched, or breached without reclaiming" };
  }

  const oppositeSwing = lastOppositeSwing(contextSwings, side);
  if (!oppositeSwing) {
    return { status: "blocked", stage: "opposite_swing", detail: "no prior swing to break for an MSS" };
  }

  const sweepIndex = input.reactionCandles.findIndex((c) => c.openTime === sweep.sweptAt);
  const postSweepCandles = input.reactionCandles.slice(sweepIndex + 1);
  const displacement = detectDisplacement(postSweepCandles, side, oppositeSwing.price, {
    atrPeriod: input.atrPeriod,
    minBodyAtrMultiple: input.minBodyAtrMultiple,
    minFvgSize: input.minFvgSize,
  });
  if (!displacement) {
    return { status: "blocked", stage: "displacement", detail: "no body-close break with a big-enough, FVG-backed candle" };
  }

  const allCandles = [...input.contextCandles, ...input.reactionCandles];
  const allSwings = detectSwings(allCandles, input.swingLookback);
  const structureShifts = detectStructureShifts(allCandles, allSwings, input.swingLookback);
  const orderBlocks = detectOrderBlocks(allCandles, structureShifts);
  const poi = pointOfInterestFor(displacement, orderBlocks, side);
  if (!poi) {
    return { status: "blocked", stage: "poi", detail: "FVG already mitigated and no usable order block" };
  }

  const entryPrice = poi.ce;
  const stop = computeStopLoss(side, sweep.wickExtreme, input.spreadBuffer, entryPrice, input.maxStopDistance);
  if (!stop) {
    return { status: "blocked", stage: "stop", detail: "stop distance exceeds the symbol's calibrated ceiling" };
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
    return { status: "blocked", stage: "gates", detail: gate.reason ?? "viability gate refused" };
  }

  return {
    status: "proposed",
    proposal: {
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
    },
  };
}

/** Thin wrapper over evaluateSetup for callers that only need the proposal
 * itself (EA-01's original shape) — unchanged behavior, no test rewritten. */
export function proposeSetup(input: SetupProposalInput): SetupProposal | null {
  const outcome = evaluateSetup(input);
  return outcome.status === "proposed" ? outcome.proposal : null;
}
