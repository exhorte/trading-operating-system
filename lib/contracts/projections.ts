/**
 * Projections: canonical domain models -> dashboard read models.
 *
 * The analysis engine emits a structured MarketContextState (lib/domain); the
 * cockpit panel renders a flattened MarketContext (lib/contracts/snapshots)
 * with human-readable notes. This is the single place that humanises the
 * structured facts. Allowed to import both layers (contracts -> domain).
 */

import type {
  LiquidityLevel,
  MarketContextState,
} from "@/lib/domain/analysis";
import type { RiskDecision, RiskPolicy, RiskState } from "@/lib/domain/risk";
import type { StrategySignal as DomainStrategySignal } from "@/lib/domain/strategy";
import type {
  MarketContext,
  RiskDecisionView,
  RiskStatus,
  StrategySignal,
} from "./snapshots";

const LIQUIDITY_LABELS: Record<LiquidityLevel["kind"], string> = {
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
  const trend =
    state.bias === "bullish" ? "Uptrend" : state.bias === "bearish" ? "Downtrend" : "Ranging";
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
    .map((l) => `${LIQUIDITY_LABELS[l.kind]} ${num(l.price)}`)
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

/** Flatten a domain RiskDecision into the dashboard's audit-grade view. */
export function toRiskDecisionView(decision: RiskDecision): RiskDecisionView {
  return {
    approvalId: decision.approvalId,
    signalId: decision.signalId,
    accountId: decision.accountId,
    approved: decision.approved,
    approvedVolume: decision.approvedVolume,
    reason: decision.reason,
    decidedAt: decision.decidedAt,
  };
}

/**
 * Flatten a domain StrategySignal into the Signal Queue read model. The frozen
 * marketContext becomes a short human summary; the risk decision (if any) fills
 * the riskDecision line.
 */
export function toStrategySignalReadModel(
  signal: DomainStrategySignal,
  decision?: RiskDecision | null,
): StrategySignal {
  const ctx = signal.marketContext;
  const structure = ctx.lastStructureShift
    ? ctx.lastStructureShift.kind === "break_of_structure"
      ? "BOS"
      : "CHOCH"
    : "ranging";
  return {
    signalId: signal.signalId,
    symbol: signal.symbol,
    strategyId: signal.strategyId,
    side: signal.side,
    status: signal.status,
    score: signal.score,
    maxScore: signal.maxScore,
    contextSummary: `${ctx.bias} bias · ${structure} · ${ctx.session}`,
    riskDecision: decision ? decision.reason : null,
    expiresAt: signal.expiresAt,
    createdAt: signal.createdAt,
  };
}

/** Flatten a domain RiskState + RiskPolicy into the panel's RiskStatus read model. */
export function toRiskStatusReadModel(state: RiskState, policy: RiskPolicy): RiskStatus {
  return {
    state: state.mode,
    dailyLossLimitPercent: policy.dailyLossLimitPercent,
    dailyLossUsedPercent: state.dailyLossUsedPercent,
    maxDrawdownLimitPercent: policy.maxDrawdownLimitPercent,
    maxDrawdownUsedPercent: state.maxDrawdownUsedPercent,
    maxTradesPerDay: policy.maxTradesPerDay,
    tradesToday: state.tradesToday,
    consecutiveLosses: state.consecutiveLosses,
    lockoutReason: state.lockoutReason,
    gates: state.gates.map((g) => ({
      gateId: g.gateId,
      label: g.label,
      state: g.state,
      detail: g.detail,
    })),
  };
}

/** Flatten a domain MarketContextState into the panel's MarketContext read model. */
export function toMarketContextReadModel(state: MarketContextState): MarketContext {
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
    scoreBreakdown: state.scoreBreakdown.map((c) => ({
      label: c.label,
      score: c.score,
      maxScore: c.maxScore,
    })),
    updatedAt: state.computedAt,
  };
}
