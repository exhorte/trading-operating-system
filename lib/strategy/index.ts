/**
 * Strategy engine — public surface. Pure and portable (imports only lib/domain
 * and lib/analysis), ported to .NET later like its siblings (ADR 0006 law).
 *
 * Iteration 1 (Phase 12 Part B) ships one entry trigger: an ICT FVG-retest
 * setup, the experimental treatment arm against the periodic sampler control.
 */

export { evaluateTrigger, type TriggerInput, type TriggerResult, type TriggerSetup } from "./trigger";
export {
  CANDIDATE_CONFIG_2026_07_18,
  DEFAULT_TRIGGER_CONFIG,
  type TriggerConfig,
  type ConfirmationClose,
} from "./config";
