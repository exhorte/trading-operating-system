/**
 * Tunable knobs for the ICT/SMC analysis engine (v0.1).
 *
 * Every value is a hypothesis, not a validated edge. Tolerances are expressed
 * in raw price units for the MVP; a later revision should derive them from ATR
 * / symbol tickSize so one config generalises across instruments.
 * See context/engineering/analysis_engine_mvp.md.
 */

import type { SessionWindow } from "@/lib/domain/market";

export interface ScoreWeights {
  /** Aligned market structure (BOS/CHOCH in bias direction). */
  structure: number;
  /** A liquidity pool was recently swept (draw-on-liquidity confirmation). */
  liquiditySweep: number;
  /** Price sits in an unmitigated PD array (FVG/OB) in the bias direction. */
  pdArray: number;
  /** Current session is a configured trading window. */
  session: number;
  /** Price is in the correct premium/discount half for the bias. */
  premiumDiscount: number;
}

export interface AnalysisConfig {
  /** Fractal strength: bars required on each side to confirm a swing. */
  swingLookback: number;
  /** Max price distance for two swing points to count as an equal high/low. */
  equalLevelTolerance: number;
  /** Minimum gap size (price units) for a 3-candle imbalance to count as an FVG. */
  minFvgSize: number;
  /** How many of the most recent swings feed structure/liquidity detection. */
  structureSwingWindow: number;
  /** UTC trading windows used to bucket timestamps into ICT sessions. */
  sessionWindows: SessionWindow[];
  /** Max points awarded per confluence component. */
  scoreWeights: ScoreWeights;
}

/**
 * Default ICT session windows in UTC. Boundaries are pragmatic MVP values
 * (not tied to DST); Silver Bullet / power-hour sub-windows are deferred.
 */
export const DEFAULT_SESSION_WINDOWS: SessionWindow[] = [
  { session: "asia", startUtc: "23:00", endUtc: "07:00", tradingEnabled: false },
  { session: "london", startUtc: "07:00", endUtc: "12:00", tradingEnabled: true },
  { session: "new_york_am", startUtc: "12:00", endUtc: "16:00", tradingEnabled: true },
  { session: "new_york_pm", startUtc: "16:00", endUtc: "20:00", tradingEnabled: false },
  { session: "off_session", startUtc: "20:00", endUtc: "23:00", tradingEnabled: false },
];

export const DEFAULT_ANALYSIS_CONFIG: AnalysisConfig = {
  swingLookback: 2,
  equalLevelTolerance: 0.3,
  minFvgSize: 0.2,
  structureSwingWindow: 12,
  sessionWindows: DEFAULT_SESSION_WINDOWS,
  scoreWeights: {
    structure: 3,
    liquiditySweep: 2,
    pdArray: 3,
    session: 1,
    premiumDiscount: 1,
  },
};

/** Sum of all component weights — the denominator of a context score. */
export function maxScoreOf(weights: ScoreWeights): number {
  return (
    weights.structure +
    weights.liquiditySweep +
    weights.pdArray +
    weights.session +
    weights.premiumDiscount
  );
}
