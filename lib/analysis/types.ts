/**
 * Engine-internal types. These are intermediate computations (swings, feature
 * bundles, price location) that do not belong in the portable domain model.
 * Only lib/domain types cross the engine boundary as output.
 */

import type { Candle } from "@/lib/domain/market";
import type { SymbolCode, Timeframe, UtcTimestamp, Bias, TradingSession } from "@/lib/domain/primitives";
import type {
  FairValueGap,
  LiquidityLevel,
  OrderBlock,
  StructureShift,
} from "@/lib/domain/analysis";
import type { AnalysisConfig } from "./config";

/** A confirmed fractal pivot. `index` refers to the source candle array. */
export interface Swing {
  kind: "high" | "low";
  price: number;
  index: number;
  time: UtcTimestamp;
}

/** Where price sits inside the most recent swing range. */
export type PriceLocation = "premium" | "equilibrium" | "discount";

/** Input to a full market-context analysis pass. */
export interface AnalysisInput {
  symbol: SymbolCode;
  timeframe: Timeframe;
  /** Chronological, oldest-first. Only closed candles should be analysed. */
  candles: Candle[];
  config?: AnalysisConfig;
}

/**
 * Intermediate feature bundle produced by the detectors and consumed by the
 * bias and scoring stages before the final MarketContextState is assembled.
 */
export interface AnalysisFeatures {
  swings: Swing[];
  structureShifts: StructureShift[];
  lastStructureShift: StructureShift | null;
  liquidity: LiquidityLevel[];
  fairValueGaps: FairValueGap[];
  orderBlocks: OrderBlock[];
  session: TradingSession;
  bias: Bias;
  priceLocation: PriceLocation;
  /** A liquidity level was swept by the most recent candles. */
  recentlySwept: boolean;
}
