# Phase 07 - Signal → Risk Review Wiring

Status: implemented 2026-07-09 (design in `phase-07-design.md`, validated first: new `risk.decision.made` event; mock becomes a mini strategy; live signals out of scope). Awaiting user review before closure.

## Objective

Replace the mock's faked signal approvals/rejects (`score >= 7`) with real, testable `RiskDecision`s from the Phase 06 `evaluateSignalRisk`, and expose them on a clean audit-grade contract — without moving to the backend.

## Scope

In scope: mock mini-strategy emitting domain `StrategySignal`s from the computed `MarketContextState`; real risk review via `evaluateSignalRisk`; new `risk.decision.made` event + `RiskDecisionPayload`/`RiskDecisionView`; projections; store handling.

Out of scope: live/observe signals (no strategy engine there); the real execution/order loop (still Phase 08 / backend); persisting decisions.

## Acceptance Criteria

- No `approved = score >= 7` anywhere; approve/reject come from a real `RiskDecision` (sizing + gates + lockout).
- `risk.decision.made` + `RiskDecisionPayload` added; `EventPayloadMap` exhaustive; store applies it (updates the signal's status + reason).
- `toStrategySignalReadModel` + `toRiskDecisionView` projected and tested.
- Rejected when risk locked / entry gate blocked; approved carries a coherent `approvedVolume`.
- `lint` / source `tsc` / `build` / `test` green.
- Phase files + brain updated.

## Implementation Notes (2026-07-09)

Added `risk.decision.made` (`envelope.ts` EventType, `RiskDecisionMadePayload` + `EventPayloadMap`, `RiskDecisionView` read model). Added projections `toStrategySignalReadModel(signal, decision?)` and `toRiskDecisionView(decision)`. New `lib/mock/signals.ts` mini strategy (side ← bias, fixed-distance stop/target, carries the frozen `MarketContextState`). `initial-snapshot` now exposes `mockRiskContext()` (domain `RiskState` + policy + balance) so the mock client reviews against the same state the panel renders; seed `sig-014` flipped off `risk_review` to avoid a stuck pending. Store handles `risk.decision.made`. `mock-client.advanceSignals` rewritten: create a domain signal from the computed context → next tick reviews it with `evaluateSignalRisk` → emit `risk.decision.made` → on approval, fill @ `approvedVolume`.

Verified: lint clean, source `tsc` exit 0, build compiles, 47 Vitest tests (3 new). Runtime sanity: bullish context → buy signal → approved, 2.02 lot at 1% risk, mode normal. The legacy `risk.command.approved/rejected` events remain in the contract (unused by the mock now).
