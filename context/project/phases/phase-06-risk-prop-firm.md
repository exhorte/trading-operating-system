# Phase 06 - Risk & Prop Firm Mode

Status: implemented 2026-07-08 (design in `phase-06-design.md`, validated by the user first: panel + gates scope; live = session baseline + honest "n/a"). Awaiting user review before closure.

## Objective

Build the first risk engine as pure TS services (engine-first pattern) that compute a `RiskState` (per-gate results + normal/warning/locked + lockout) from account + positions + a `RiskPolicy`, filling the Risk Status panel and risk KPI tiles in both mock and live.

## Scope

In scope: gates (daily loss, max drawdown, open risk, max trades, consecutive losses, spread, session; news = stub), mode/lockout derivation, `evaluateSignalRisk`→`RiskDecision` (built + tested, not wired), read-model projection, wiring into mock + live.

Deferred (ADR 0008): news calendar, trailing drawdown, profit-target lockout, Friday/Sunday blocks, cooldown, ATR gate, multi-symbol sizing, and wiring the signal → risk-review → execution loop.

## Acceptance Criteria

- `evaluateRiskState(input)` returns a valid `RiskState` importing only `lib/domain`; every gate implemented + unit-tested (open/blocked, mode transitions, lockout).
- `toRiskStatusReadModel` projection implemented + tested.
- Risk panel + risk KPI tiles render computed values in mock; in live, real gates where data exists and honest "n/a" otherwise.
- `lint` / source `tsc` / `build` / `test` green.
- ADR 0008 + risk engine doc + phase files + brain updated.

## Implementation Notes (2026-07-08)

Built `lib/risk/`: `policy` (`defaultRiskPolicy`, `WARNING_THRESHOLD`), `types`, `open-risk` (excludes sl≤0 positions), `gates` (one pure fn per guard, "n/a" on unknown input), `evaluate` (`evaluateRiskState`), `sizing` (`evaluateSignalRisk`→`RiskDecision`, not wired), `index`. Made `RiskState`/`RiskStatus` `tradesToday`/`consecutiveLosses` `number | null` (honest "n/a"); panel renders "n/a". Added `toRiskStatusReadModel` projection. Wired mock (`mockRisk` computes) and live (`LiveRealtimeClient` captures a session baseline and computes risk from real account/positions/spread/session; trade-history gates = "n/a").

Handled a real live edge case (from the Phase 05 run): the demo position had SL 0.00 → excluded from open-risk instead of a nonsensical `|entry−0|`.

Verified: lint clean, source `tsc` exit 0, build compiles, 44 Vitest tests (15 new). Engine is v0.1 — a hypothesis, not a validated edge.
