/**
 * Pure helpers for T01 (position-sizing panel). Adapts the cockpit's live
 * read models (RiskStatus + AccountSummary, from lib/contracts/snapshots)
 * into the domain RiskState that evaluateSignalRisk expects, and derives the
 * figures the fiche asks for that sizing.ts does not return on its own
 * (target vs real risk, daily-loss-budget share). Does not modify or
 * duplicate the sizing/rounding logic in lib/risk/sizing.ts.
 *
 * XAUUSD only, matching the rest of the cockpit today (mock data, positions,
 * and the "1.00 price move on 1.0 lot ≈ 100 USD" constant in sizing.ts all
 * assume XAUUSD; there is no second symbol anywhere in the product yet).
 */

import { evaluateSignalRisk } from "./sizing";
import { defaultRiskPolicy } from "./policy";
import type { AccountId, UtcTimestamp } from "@/lib/domain/primitives";
import type { RiskDecision, RiskGateResult, RiskPolicy, RiskState } from "@/lib/domain/risk";
import type { AccountSummary, RiskStatus } from "@/lib/contracts/snapshots";

/** XAUUSD: 1.00 price move on 1.0 lot ≈ 100 USD — same constant as lib/risk/sizing.ts. */
const XAUUSD_USD_PER_POINT_PER_LOT = 100;

/** Same point convention already used for spread in lib/risk/policy.ts: 1 point = 0.01. */
const PRICE_PER_POINT = 0.01;
/** Standard broker convention for XAUUSD: 1 pip = 10 points = 0.10. */
const POINTS_PER_PIP = 10;

/** Tolerance for float rounding when comparing real risk to the target budget. */
const FLOOR_EPSILON = 1.0001;

export interface SizingPanelInput {
  entryPrice: number;
  stopLoss: number;
  takeProfit: number | null;
  account: AccountSummary;
  risk: RiskStatus;
  now: UtcTimestamp;
}

export interface SizingPanelResult {
  /** Null until entry and stop describe a valid, non-zero distance. */
  stopDistance: number | null;
  stopDistancePoints: number | null;
  stopDistancePips: number | null;
  /** Null unless a take-profit is provided, on the correct side, and the stop distance is valid. */
  rMultipleTarget: number | null;
  /** True when a take-profit was entered on the wrong side of entry for this stop (never a fake R). */
  takeProfitInvalid: boolean;
  policy: RiskPolicy;
  /** Null when there is no valid stop distance to size against. */
  decision: RiskDecision | null;
  /** Risk budget the policy targets for this trade, independent of rounding. */
  targetRiskUsd: number | null;
  /** Actual dollar risk once the 0.01-lot floor (sizing.ts) is applied. */
  realRiskUsd: number | null;
  realRiskPercent: number | null;
  /** True when the 0.01-lot floor pushed the real risk above the target. */
  floorApplied: boolean;
  /** Share of TODAY'S REMAINING authorized daily-loss budget (limit minus what's
   *  already used) this trade would consume if stopped out — not a share of the
   *  total limit, which would understate the danger once losses have accumulated. */
  dailyBudgetConsumedPercent: number | null;
  gates: RiskGateResult[];
}

/**
 * Thin adapter: RiskStatus (display projection) + AccountSummary carry every
 * field evaluateSignalRisk actually reads off RiskState (mode, gates,
 * lockoutReason) — this just renames/regroups them, it computes nothing.
 */
function toRiskStateForSizing(
  risk: RiskStatus,
  accountId: AccountId,
  openRiskPercent: number,
  now: UtcTimestamp,
): RiskState {
  return {
    accountId,
    mode: risk.state,
    dailyLossUsedPercent: risk.dailyLossUsedPercent,
    maxDrawdownUsedPercent: risk.maxDrawdownUsedPercent,
    openRiskPercent,
    tradesToday: risk.tradesToday,
    consecutiveLosses: risk.consecutiveLosses,
    lockoutReason: risk.lockoutReason,
    // RiskStatus (lib/contracts/snapshots.ts) has no lockoutUntil field yet —
    // T02 will need to add it there (and to its C# mirror in
    // backend/src/TradingOs.Contracts/ReadModels.cs) for the pause clock to
    // ever reach the cockpit. Hardcoded null until then.
    lockoutUntil: null,
    gates: risk.gates,
    evaluatedAt: now,
  };
}

export function computeSizingPanel(input: SizingPanelInput): SizingPanelResult {
  const { entryPrice, stopLoss, takeProfit, account, risk, now } = input;
  const policy = defaultRiskPolicy(account.accountId);
  const gates = risk.gates;

  const rawDistance = entryPrice - stopLoss;
  const stopDistance =
    Number.isFinite(rawDistance) && rawDistance !== 0 ? Math.abs(rawDistance) : null;
  const stopDistancePoints = stopDistance !== null ? stopDistance / PRICE_PER_POINT : null;
  const stopDistancePips = stopDistancePoints !== null ? stopDistancePoints / POINTS_PER_PIP : null;

  // A take-profit is only meaningful on the opposite side of entry from the
  // stop: reward = takeProfit - entryPrice must carry the same sign as
  // (entryPrice - stopLoss) (positive = long, negative = short). A TP on the
  // wrong side (or exactly at entry) is flagged, never silently turned into a
  // positive-looking R via Math.abs.
  let rMultipleTarget: number | null = null;
  let takeProfitInvalid = false;
  if (stopDistance !== null && takeProfit !== null) {
    const reward = takeProfit - entryPrice;
    const stopSide = entryPrice - stopLoss;
    if (reward === 0 || Math.sign(reward) !== Math.sign(stopSide)) {
      takeProfitInvalid = true;
    } else {
      rMultipleTarget = Math.abs(reward) / stopDistance;
    }
  }

  if (stopDistance === null) {
    return {
      stopDistance: null,
      stopDistancePoints: null,
      stopDistancePips: null,
      rMultipleTarget,
      takeProfitInvalid,
      policy,
      decision: null,
      targetRiskUsd: null,
      realRiskUsd: null,
      realRiskPercent: null,
      floorApplied: false,
      dailyBudgetConsumedPercent: null,
      gates,
    };
  }

  const state = toRiskStateForSizing(risk, account.accountId, account.openRiskPercent, now);
  const decision = evaluateSignalRisk({
    signalId: "sizing-panel-preview",
    accountId: account.accountId,
    entryPrice,
    stopLoss,
    balance: account.balance,
    state,
    policy,
    now,
  });

  const targetRiskUsd = (account.balance * policy.maxRiskPerTradePercent) / 100;

  let realRiskUsd: number | null = null;
  let realRiskPercent: number | null = null;
  let floorApplied = false;
  let dailyBudgetConsumedPercent: number | null = null;

  if (decision.approved && decision.approvedVolume !== null) {
    realRiskUsd = stopDistance * decision.approvedVolume * XAUUSD_USD_PER_POINT_PER_LOT;
    realRiskPercent = (realRiskUsd / account.balance) * 100;
    floorApplied = realRiskUsd > targetRiskUsd * FLOOR_EPSILON;
    // Remaining budget, not the total limit: dailyLossUsedPercent is already
    // spent, so what's left is (limit - used). A gate rejection (mode
    // "locked" or dailyLossGate blocked) would already have set
    // decision.approved = false above whenever used >= limit, so this stays
    // positive here — but guard it anyway rather than trust that invariant.
    const dailyLossRemainingUsd =
      (account.balance * (risk.dailyLossLimitPercent - risk.dailyLossUsedPercent)) / 100;
    dailyBudgetConsumedPercent =
      dailyLossRemainingUsd > 0 ? (realRiskUsd / dailyLossRemainingUsd) * 100 : null;
  }

  return {
    stopDistance,
    stopDistancePoints,
    stopDistancePips,
    rMultipleTarget,
    takeProfitInvalid,
    policy,
    decision,
    targetRiskUsd,
    realRiskUsd,
    realRiskPercent,
    floorApplied,
    dailyBudgetConsumedPercent,
    gates,
  };
}
