/**
 * Iteration-1 entry-trigger knobs (Phase 12 Part B). Every value is fixed a
 * priori by convention and is NOT tuned in this iteration — tuning any single
 * knob is a separate future iteration, one hypothesis at a time (ADR 0013).
 *
 * The experiment compares a real entry condition against the periodic sampler;
 * nothing about the score, sessions, days, Risk Engine, or the 2R target is
 * touched here.
 */

export type ConfirmationClose = "lenient" | "middle" | "strict";

export interface TriggerConfig {
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
  maxShiftAgeBars: 12,
  maxSetupAgeBars: 12,
  atrPeriod: 14,
  atrBufferMultiple: 0.5,
  minStopTicks: 1,
  rewardMultiple: 2,
  confirmationClose: "middle",
};
