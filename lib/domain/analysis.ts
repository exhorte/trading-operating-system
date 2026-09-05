/**
 * ICT/SMC analysis models: liquidity, PD arrays, structure, market context.
 * These are the structured facts the analysis engine emits so every trade
 * decision stays traceable to market context (explainability requirement).
 * Vocabulary source: context/domain/ict_smc_framework.md.
 */

import type {
  Bias,
  SymbolCode,
  Timeframe,
  TradingSession,
  UtcTimestamp,
} from "./primitives";

export type LiquidityKind =
  | "buy_side"
  | "sell_side"
  | "equal_highs"
  | "equal_lows"
  | "session_high"
  | "session_low"
  | "previous_day_high"
  | "previous_day_low";

/** A resting-liquidity level the market may draw toward or sweep. */
export interface LiquidityLevel {
  levelId: string;
  symbol: SymbolCode;
  timeframe: Timeframe;
  kind: LiquidityKind;
  price: number;
  /** Null while the level is intact; set when swept. */
  sweptAt: UtcTimestamp | null;
  detectedAt: UtcTimestamp;
}

/** Fair value gap (imbalance) between candle 1 and candle 3. */
export interface FairValueGap {
  fvgId: string;
  symbol: SymbolCode;
  timeframe: Timeframe;
  direction: Bias;
  /** Upper and lower bounds of the gap. */
  high: number;
  low: number;
  /** How much of the gap has been filled, 0-100. */
  filledPercent: number;
  /** Null while the gap remains unmitigated. */
  mitigatedAt: UtcTimestamp | null;
  detectedAt: UtcTimestamp;
}

/** Order block: last opposing candle range before a displacement move. */
export interface OrderBlock {
  orderBlockId: string;
  symbol: SymbolCode;
  timeframe: Timeframe;
  direction: Bias;
  high: number;
  low: number;
  /** Null while price has not returned to the block. */
  mitigatedAt: UtcTimestamp | null;
  detectedAt: UtcTimestamp;
}

export type StructureShiftKind =
  | "break_of_structure"
  | "change_of_character"
  | "liquidity_sweep_reversal";

/** A confirmed market-structure event on one timeframe. */
export interface StructureShift {
  shiftId: string;
  symbol: SymbolCode;
  timeframe: Timeframe;
  kind: StructureShiftKind;
  direction: Bias;
  /** Price level whose break confirmed the shift. */
  brokenLevel: number;
  occurredAt: UtcTimestamp;
}

/** One weighted component of a context/setup confluence score. */
export interface ScoreComponent {
  label: string;
  score: number;
  maxScore: number;
}

/**
 * Aggregated analysis state for one symbol: the "why" snapshot attached to
 * signals and audit trails. Referenced entities are embedded (not ids) so a
 * stored context stays replayable without joins.
 */
export interface MarketContextState {
  symbol: SymbolCode;
  /** Primary analysis timeframe this state was computed on. */
  timeframe: Timeframe;
  bias: Bias;
  session: TradingSession;
  lastStructureShift: StructureShift | null;
  activeLiquidityLevels: LiquidityLevel[];
  activeFairValueGaps: FairValueGap[];
  activeOrderBlocks: OrderBlock[];
  /** Confluence score for the current context. */
  score: number;
  maxScore: number;
  scoreBreakdown: ScoreComponent[];
  computedAt: UtcTimestamp;
}
