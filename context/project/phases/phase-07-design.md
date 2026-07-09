# Phase 07 Design - Signal → Risk Review Wiring

Status: validated by the user on 2026-07-09 (new `risk.decision.made` event contract; mock becomes a mini strategy producing domain signals; live signals out of scope) and implemented the same day. Completion notes in `phase-07-signal-risk-review.md`.

## Objective

Replace the mock's fake `score >= 7` approvals with real, testable `RiskDecision`s from `evaluateSignalRisk` (Phase 06), on a clean audit-grade contract. No backend move.

## Existing Context

- Domain `StrategySignal` (`lib/domain/strategy.ts`) has `entryPrice`/`stopLoss`/`takeProfit`/`marketContext` — everything risk sizing needs. The read model (`snapshots.ts`) is a UI projection without those.
- `evaluateSignalRisk(...) → RiskDecision` exists + tested (Phase 06), unwired.
- `mock-client.advanceSignals` invented read-model signals and faked approve/reject.
- Handoff (Phase 02): risk decisions reached the dashboard only via `SignalUpdatedPayload`; the decision-grade record is `RiskDecision` — corrected here.

## Impact Analysis

- Mock becomes a mini strategy: domain signals from the computed `MarketContextState` (Phase 04), reviewed by the real risk engine (Phase 06) against the domain `RiskState`.
- New contract `risk.decision.made` + `RiskDecisionPayload` (+ `RiskDecisionView`); `EventPayloadMap` stays exhaustive.
- Store applies `risk.decision.made` → updates the signal (status + reason). UI unchanged (signal card already renders `riskDecision`).
- Live/observe out of scope (no strategy engine there).

## Proposed Architecture

`lib/mock/signals.ts` (mock strategy) → `StrategySignal` domain → `evaluateSignalRisk` → `RiskDecision`. Projections `toStrategySignalReadModel` / `toRiskDecisionView` in `lib/contracts/projections.ts`. `initial-snapshot.mockRiskContext()` exposes the domain `RiskState` + policy + balance so panel and review share one state.

## Data Flow

```text
MarketContextState → mock strategy → StrategySignal (domain, risk_review)
  → evaluateSignalRisk(signal, RiskState, policy, balance) → RiskDecision
  → risk.decision.made (audit-grade) + signal approved/rejected + reason
  → (if approved) execution report @ approvedVolume
```

## Files To Create Or Modify

Create: `lib/mock/signals.ts`, `lib/contracts/projections-signal.test.ts`, phase-07 files.
Modify: `lib/contracts/{envelope.ts, events.ts, snapshots.ts, projections.ts}`, `lib/realtime/{store.ts, mock-client.ts}`, `lib/mock/initial-snapshot.ts`, brain.

## Risks

- Exhaustive `EventPayloadMap` → adding an EventType is a compile gate (intended).
- Domain ↔ read-model divergence → covered by the tested projection.
- Over-scope into execution → stop at the existing mock fill report.
- A blocked entry gate in the mock risk context would reject every signal → mock uses an open NY-AM session so approvals flow.

## Acceptance Criteria

See `phase-07-signal-risk-review.md`.

## Implementation Checklist

1. [x] `risk.decision.made` (envelope + events + map) + `RiskDecisionView`.
2. [x] `toStrategySignalReadModel` + `toRiskDecisionView` (+ tests).
3. [x] `lib/mock/signals.ts` mini strategy.
4. [x] Store handles `risk.decision.made`; `mockRiskContext` export.
5. [x] Rewrite `advanceSignals` with real `evaluateSignalRisk`.
6. [x] Verify lint / source tsc / build / test.
7. [x] Phase files + brain.
