/**
 * Iteration-1 entry-trigger knobs (Phase 12 Part B). Every value is fixed a
 * priori by convention and is NOT tuned in this iteration — tuning any single
 * knob is a separate future iteration, one hypothesis at a time (ADR 0013).
 *
 * The experiment compares a real entry condition against the periodic sampler;
 * nothing about the score, sessions, days, Risk Engine, or the 2R target is
 * touched here.
 */

import type { TradingSession } from "@/lib/domain/primitives";

export type ConfirmationClose = "lenient" | "middle" | "strict";

export interface TriggerConfig {
  /**
   * Sessions the strategy may trade; null = all (iteration-1 behavior).
   * Iteration 2 passes ["new_york_am"] — the restriction lives HERE, in the
   * strategy layer: the Risk Engine's session gate is a safety control and
   * keeps its own config (a strategy choosing when to trade is not a risk
   * override).
   */
  allowedSessions: TradingSession[] | null;
  /** Max bars between the structure shift and the current bar. ~3h on M15. */
  maxShiftAgeBars: number;
  /** Max bars between the FVG's formation and the current (retest) bar. */
  maxSetupAgeBars: number;
  /** Wilder ATR period for the stop buffer. The standard, to avoid a free knob. */
  atrPeriod: number;
  /** Stop buffer beyond structural invalidation, in ATR multiples. */
  atrBufferMultiple: number;
  /** Floor on the stop buffer, in ticks, so dead volatility can't collapse it. */
  minStopTicks: number;
  /** Reward:risk. Fixed at 2R by experiment constraint — do not change here. */
  rewardMultiple: number;
  /**
   * Confirmation-close strictness on the first-retest bar (fixed a priori):
   *  - lenient: closes in the bias direction;
   *  - middle:  closes in the bias direction AND holds the gap (chosen);
   *  - strict:  closes fully beyond the gap.
   */
  confirmationClose: ConfirmationClose;
}

export const DEFAULT_TRIGGER_CONFIG: TriggerConfig = {
  allowedSessions: null,
  maxShiftAgeBars: 12,
  maxSetupAgeBars: 12,
  atrPeriod: 14,
  atrBufferMultiple: 0.5,
  minStopTicks: 1,
  rewardMultiple: 2,
  confirmationClose: "middle",
};

/**
 * FROZEN CANDIDATE — Phase 12 outcome, fixed 2026-07-18 (user decision).
 *
 * The configuration that produced runs bt-mrp973lv-965814cc (iteration 1,
 * all sessions) and bt-mrpq4try-b20fc81b (iteration 2, NY AM: train n=270
 * +0.23R, validation n=76 +0.21R — bit-identical invariant test).
 *
 * Deliberately spelled out literally, NOT spread from DEFAULT_TRIGGER_CONFIG:
 * a drift of the default must never silently move the candidate. A unit test
 * locks every value. Changing anything here is creating a NEW candidate, not
 * editing this one. NY AM was selected post-hoc from iteration 1's report, so
 * this candidate's only remaining verdict is the Phase 13 virgin holdout plus
 * net-of-costs metrics — until then it is promising, NOT validated.
 */
export const CANDIDATE_CONFIG_2026_07_18: TriggerConfig = {
  allowedSessions: ["new_york_am"],
  maxShiftAgeBars: 12,
  maxSetupAgeBars: 12,
  atrPeriod: 14,
  atrBufferMultiple: 0.5,
  minStopTicks: 1,
  rewardMultiple: 2,
  confirmationClose: "middle",
};
