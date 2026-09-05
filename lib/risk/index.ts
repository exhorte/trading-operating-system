/**
 * Risk engine (v0.1) — public surface.
 *
 * Pure, portable FTMO-style risk services: evaluate account risk state and size
 * per-signal decisions. Imports only lib/domain. See
 * context/engineering/risk_engine_mvp.md and ADR 0008. Thresholds are a
 * hypothesis, not a validated edge.
 */

export { evaluateRiskState } from "./evaluate";
export { evaluateSignalRisk, type SignalRiskInput } from "./sizing";
export { openRiskPercent, positionRiskUsd } from "./open-risk";
export { defaultRiskPolicy, WARNING_THRESHOLD } from "./policy";
export type { RiskEvaluationInput, OpenRiskPosition } from "./types";
