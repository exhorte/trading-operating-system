/**
 * Confluence scoring: turn the detected features into a weighted, testable
 * score with a per-component breakdown. This is the "why" behind a context and
 * is a hypothesis only — weights are not a validated edge.
 */

import type { Bias } from "@/lib/domain/primitives";
import type { FairValueGap, OrderBlock, ScoreComponent } from "@/lib/domain/analysis";
import type { ScoreWeights } from "./config";
import type { AnalysisFeatures } from "./types";

export interface ScoreResult {
  score: number;
  maxScore: number;
  breakdown: ScoreComponent[];
}

export interface ScoreInput {
  features: AnalysisFeatures;
  currentPrice: number;
  sessionEnabled: boolean;
  weights: ScoreWeights;
}

/** Award for an unmitigated PD array aligned with bias: full if price is inside it, half if it merely exists. */
function pdArrayScore(
  bias: Bias,
  price: number,
  fvgs: FairValueGap[],
  orderBlocks: OrderBlock[],
  weight: number,
): number {
  if (bias === "neutral") {
    return 0;
  }
  const aligned = [
    ...fvgs.filter((g) => g.direction === bias && g.mitigatedAt === null),
    ...orderBlocks.filter((o) => o.direction === bias && o.mitigatedAt === null),
  ];
  if (aligned.length === 0) {
    return 0;
  }
  const priceInside = aligned.some((a) => price >= a.low && price <= a.high);
  return priceInside ? weight : Math.round(weight / 2);
}

export function scoreContext(input: ScoreInput): ScoreResult {
  const { features, currentPrice, sessionEnabled, weights } = input;
  const { bias, lastStructureShift, recentlySwept, priceLocation } = features;

  const structure = bias !== "neutral" && lastStructureShift ? weights.structure : 0;
  const liquiditySweep = recentlySwept ? weights.liquiditySweep : 0;
  const pdArray = pdArrayScore(
    bias,
    currentPrice,
    features.fairValueGaps,
    features.orderBlocks,
    weights.pdArray,
  );
  const session = sessionEnabled ? weights.session : 0;
  const premiumDiscount =
    (bias === "bullish" && priceLocation === "discount") ||
    (bias === "bearish" && priceLocation === "premium")
      ? weights.premiumDiscount
      : 0;

  const breakdown: ScoreComponent[] = [
    { label: "Structure", score: structure, maxScore: weights.structure },
    { label: "Liquidity", score: liquiditySweep, maxScore: weights.liquiditySweep },
    { label: "PD arrays", score: pdArray, maxScore: weights.pdArray },
    { label: "Session", score: session, maxScore: weights.session },
    { label: "Prem/Disc", score: premiumDiscount, maxScore: weights.premiumDiscount },
  ];

  return {
    score: breakdown.reduce((sum, c) => sum + c.score, 0),
    maxScore: breakdown.reduce((sum, c) => sum + c.maxScore, 0),
    breakdown,
  };
}
