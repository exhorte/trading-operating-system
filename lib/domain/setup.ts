/**
 * S01 setup-proposal model: what the detection pipeline (lib/setup/) hands
 * upstream once every step of the sweep-aligned sequence has passed. A
 * strategy proposes; the Risk Engine decides (ADR 0007) — nothing here is a
 * decision, and nothing here has been sized or approved yet.
 *
 * Deliberately distinct from StrategySignal (./strategy.ts): that type
 * carries a post-Risk-Engine lifecycle (risk_review, commanded, ...) that
 * has no meaning before EA-03 wires this into execution. Vocabulary source:
 * context/product/tools/S01-strategie-sweep-aligne.md.
 */

import type { LiquidityKind } from "./analysis";
import type { Side, SymbolCode, UtcTimestamp } from "./primitives";

/** A completed S01 setup proposal. Never an order, never a decision. */
export interface SetupProposal {
  proposalId: string;
  symbol: SymbolCode;
  side: Side;
  /** The liquidity pool whose sweep triggered this proposal (S01 step 4). */
  sweptLevelKind: LiquidityKind;
  sweptLevelPrice: number;
  entryPrice: number;
  stopLoss: number;
  /** Opposite external liquidity — the trade's objective (S01 step 3). */
  takeProfit: number;
  /** c = round-trip cost / stop distance (S01, "porte de coût"). */
  costRatio: number;
  /** R:R from entry to takeProfit, after cost (S01, "porte R:R"). */
  riskRewardRatio: number;
  detectedAt: UtcTimestamp;
}

/** Where the S01 sequence stopped when it doesn't reach a proposal — the
 * whole point of EA-02's measurement (S01: "l'étape exacte à laquelle la
 * séquence s'est arrêtée... dit POURQUOI la machine n'a rien proposé").
 * The five "precondition_*" stages are evaluated by whatever orchestrates
 * lib/setup/ live (EA-02's worker) BEFORE the pure pipeline ever runs —
 * S01: "si une seule [précondition] manque, il n'y a pas de recherche" —
 * they are not returned by lib/setup/proposal.ts itself. */
export type SetupStage =
  | "precondition_session_window"
  | "precondition_ny_lunch"
  | "precondition_calendar"
  | "precondition_lockout"
  | "precondition_trades_limit"
  | "bias"
  | "dealing_range"
  | "range_location"
  | "liquidity"
  | "sweep"
  | "opposite_swing"
  | "displacement"
  | "poi"
  | "stop"
  | "gates";

export type SetupOutcome =
  | { status: "proposed"; proposal: SetupProposal }
  | { status: "blocked"; stage: SetupStage; detail: string };
