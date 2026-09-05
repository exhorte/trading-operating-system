/**
 * Orchestrator: run every detector over a candle series and assemble the
 * canonical MarketContextState (the traceable "why" snapshot for one symbol).
 *
 * Pure and portable — imports only lib/domain and sibling engine modules, never
 * lib/contracts, lib/realtime, or UI. Analysis is computed at the last closed
 * candle; nothing here reads future bars.
 */

import type { MarketContextState } from "@/lib/domain/analysis";
import { DEFAULT_ANALYSIS_CONFIG, maxScoreOf } from "./config";
import { computeBias, priceLocationOf } from "./bias";
import { detectLiquidity } from "./liquidity";
import { detectFairValueGaps, detectOrderBlocks } from "./pd-arrays";
import { scoreContext } from "./scoring";
import { sessionEnabled, sessionForTimestamp } from "./sessions";
import { detectStructureShifts, structuralBias } from "./structure";
import { detectSwings } from "./swings";
import type { AnalysisFeatures, AnalysisInput } from "./types";

/** How many trailing candles count as a "recent" liquidity sweep. */
const RECENT_SWEEP_WINDOW = 3;

export function analyzeMarketContext(input: AnalysisInput): MarketContextState {
  const cfg = input.config ?? DEFAULT_ANALYSIS_CONFIG;
  const { candles } = input;

  if (candles.length === 0) {
    return {
      symbol: input.symbol,
      timeframe: input.timeframe,
      bias: "neutral",
      session: "off_session",
      lastStructureShift: null,
      activeLiquidityLevels: [],
      activeFairValueGaps: [],
      activeOrderBlocks: [],
      score: 0,
      maxScore: maxScoreOf(cfg.scoreWeights),
      scoreBreakdown: [],
      computedAt: new Date(0).toISOString(),
    };
  }

  const lastCandle = candles[candles.length - 1];
  const currentPrice = lastCandle.close;

  const swings = detectSwings(candles, cfg.swingLookback);
  const structureShifts = detectStructureShifts(candles, swings, cfg.swingLookback);
  const lastStructureShift = structureShifts.at(-1) ?? null;
  const bias = computeBias(structuralBias(structureShifts));

  const liquidity = detectLiquidity(candles, swings, cfg.equalLevelTolerance);
  const fairValueGaps = detectFairValueGaps(candles, cfg.minFvgSize);
  const orderBlocks = detectOrderBlocks(candles, structureShifts);

  const session = sessionForTimestamp(lastCandle.openTime, cfg.sessionWindows);
  const priceLocation = priceLocationOf(currentPrice, swings);

  const recentFrom =
    candles[Math.max(0, candles.length - RECENT_SWEEP_WINDOW)].openTime;
  const recentlySwept = liquidity.some(
    (level) => level.sweptAt !== null && level.sweptAt >= recentFrom,
  );

  const features: AnalysisFeatures = {
    swings,
    structureShifts,
    lastStructureShift,
    liquidity,
    fairValueGaps,
    orderBlocks,
    session,
    bias,
    priceLocation,
    recentlySwept,
  };

  const { score, maxScore, breakdown } = scoreContext({
    features,
    currentPrice,
    sessionEnabled: sessionEnabled(session, cfg.sessionWindows),
    weights: cfg.scoreWeights,
  });

  return {
    symbol: input.symbol,
    timeframe: input.timeframe,
    bias,
    session,
    lastStructureShift,
    activeLiquidityLevels: liquidity.filter((l) => l.sweptAt === null),
    activeFairValueGaps: fairValueGaps.filter((g) => g.mitigatedAt === null),
    activeOrderBlocks: orderBlocks.filter((o) => o.mitigatedAt === null),
    score,
    maxScore,
    scoreBreakdown: breakdown,
    computedAt: lastCandle.openTime,
  };
}
