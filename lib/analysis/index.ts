/**
 * ICT/SMC analysis engine (v0.1) — public surface.
 *
 * Consumes Candle[] and emits the canonical MarketContextState from lib/domain.
 * Pure and transport-agnostic; see context/engineering/analysis_engine_mvp.md
 * for scope, the no-look-ahead rule, and the deferred engines.
 */

export { analyzeMarketContext } from "./market-context";
export { averageTrueRange } from "./atr";
export {
  DEFAULT_ANALYSIS_CONFIG,
  DEFAULT_SESSION_WINDOWS,
  maxScoreOf,
} from "./config";
export type { AnalysisConfig, ScoreWeights } from "./config";
export type { AnalysisInput, AnalysisFeatures, Swing, PriceLocation } from "./types";
