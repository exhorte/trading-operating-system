/**
 * The market context, put into the words the panel shows.
 *
 * The core's analysis answers with structure (`MarketContextState`: a bias, the last shift, the open levels and gaps, a score
 * and what it is made of). The panel wants sentences. This is the one place the facts are phrased, and it phrases only: it
 * adds nothing the analysis did not say. Levels are context, never signals (ADR 0002).
 */

import type { LiquidityKind, MarketContextState, ScoreComponent } from "@/lib/api/generated";

export interface MarketContextView {
  symbol: string;
  timeframe: string;
  bias: MarketContextState["bias"];
  structureState: string;
  lastStructureEvent: string;
  session: MarketContextState["session"];
  liquidityNote: string;
  pdArrayNote: string;
  score: number;
  maxScore: number;
  scoreBreakdown: ScoreComponent[];
  updatedAt: string;
}

const LIQUIDITY_LABELS: Record<LiquidityKind, string> = {
  buy_side: "Buy-side",
  sell_side: "Sell-side",
  equal_highs: "Equal highs",
  equal_lows: "Equal lows",
  session_high: "Session high",
  session_low: "Session low",
  previous_day_high: "PDH",
  previous_day_low: "PDL",
};

function num(value: number): string {
  return value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function structureState(state: MarketContextState): string {
  const trend = state.bias === "bullish" ? "Uptrend" : state.bias === "bearish" ? "Downtrend" : "Ranging";
  if (!state.lastStructureShift) {
    return trend;
  }
  const tag = state.lastStructureShift.kind === "break_of_structure" ? "BOS" : "CHOCH";
  return `${trend} after ${tag}`;
}

function lastStructureEvent(state: MarketContextState): string {
  const shift = state.lastStructureShift;
  if (!shift) {
    return "No confirmed shift";
  }
  const tag = shift.kind === "break_of_structure" ? "BOS" : "CHOCH";
  const side = shift.direction === "bullish" ? "above" : "below";
  return `${tag} ${side} ${num(shift.brokenLevel)} (${shift.timeframe})`;
}

function liquidityNote(state: MarketContextState): string {
  if (state.activeLiquidityLevels.length === 0) {
    return "No tracked pools";
  }
  return state.activeLiquidityLevels
    .slice(0, 3)
    .map((level) => `${LIQUIDITY_LABELS[level.kind]} ${num(level.price)}`)
    .join(", ");
}

function pdArrayNote(state: MarketContextState): string {
  const parts: string[] = [];
  const fvg = state.activeFairValueGaps[0];
  if (fvg) {
    parts.push(`${fvg.direction} FVG ${num(fvg.low)}-${num(fvg.high)}`);
  }
  const ob = state.activeOrderBlocks[0];
  if (ob) {
    parts.push(`${ob.direction} OB ${num(ob.low)}-${num(ob.high)}`);
  }
  return parts.length > 0 ? parts.join("; ") : "No active PD arrays";
}

export function toMarketContextView(state: MarketContextState): MarketContextView {
  return {
    symbol: state.symbol,
    timeframe: state.timeframe,
    bias: state.bias,
    structureState: structureState(state),
    lastStructureEvent: lastStructureEvent(state),
    session: state.session,
    liquidityNote: liquidityNote(state),
    pdArrayNote: pdArrayNote(state),
    score: state.score,
    maxScore: state.maxScore,
    scoreBreakdown: state.scoreBreakdown.map((component) => ({
      label: component.label,
      score: component.score,
      maxScore: component.maxScore,
    })),
    updatedAt: state.computedAt,
  };
}
