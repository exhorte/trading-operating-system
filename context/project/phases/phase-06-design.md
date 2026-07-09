# Phase 06 Design - Risk & Prop Firm Mode

Status: validated by the user on 2026-07-08 (scope = risk panel + gates; `evaluateSignalRisk` built+tested but not wired; live = session baseline + honest "n/a") and implemented the same day. Completion notes in `phase-06-risk-prop-firm.md`.

## Objective

First risk engine as pure TS services computing a `RiskState` from account + positions + `RiskPolicy`, projected to the `RiskStatus` read model — filling the empty Risk Status panel and "—" risk KPI tiles in mock and live.

## Existing Context

- Domain ready: `lib/domain/risk.ts` (`RiskPolicy`, `RiskState`, `RiskGateResult`, `RiskDecision`); guard list in `context/domain/risk_ftmo.md`.
- Read model `RiskStatus` (`lib/contracts/snapshots.ts`); store applies `risk.state.updated`.
- `mockRisk()` hard-coded the panel; live set `risk = null`. Both replaced by computed output.
- Phase 05 live run showed the observe producer has no trade history (trades/consecutive unknown) and positions may have no SL.

## Impact Analysis

- New pure layer `lib/risk/` (imports only `lib/domain`), next to `lib/analysis`.
- Projection `toRiskStatusReadModel(state, policy)` in `lib/contracts/projections.ts`.
- `RiskState`/`RiskStatus` `tradesToday`/`consecutiveLosses` → `number | null` (honest "n/a"); panel renders "n/a".
- Mock: `mockRisk` computes. Live: `LiveRealtimeClient` captures a session baseline + evaluates risk from real data.
- No new deps; engine-first, backend-later pattern.

## Proposed Architecture

`lib/risk/`: `policy`, `types`, `open-risk`, `gates` (one pure fn per guard), `evaluate` (`evaluateRiskState`), `sizing` (`evaluateSignalRisk`→`RiskDecision`, not wired), `index`. Posture: locked on account-level breach (daily loss/drawdown/max trades/consecutive), warning ≥60% of a limit, else normal; spread/session/open-risk are entry gates. Drawdown static-vs-initial for MVP. All v0.1 hypotheses.

## Data Flow

```text
account + positions + policy + baseline (+ spread, session)
  → evaluateRiskState() → RiskState → toRiskStatusReadModel() → RiskStatus
  → risk.state.updated / hydrate → Risk panel + KPI risk tiles
```
Mock: full inputs. Live: real account/positions/spread/session; trades & consecutive = null → "n/a".

## Files To Create Or Modify

Create: `lib/risk/*` (+ tests), `lib/contracts/projections-risk.test.ts`, `context/adr/0008-risk-engine-typescript.md`, `context/engineering/risk_engine_mvp.md`, this design + the phase file.
Modify: `lib/domain/risk.ts` + `lib/contracts/snapshots.ts` (nullable counts), `lib/contracts/projections.ts` (+projection), `components/cockpit/risk-status-panel.tsx` ("n/a"), `lib/mock/initial-snapshot.ts` (`mockRisk` computes), `lib/realtime/live-client.ts` (baseline + risk), project brain.

## Risks

- Presenting thresholds as validated → v0.1 label, hypothesis framing.
- Symbol-specific open-risk factor (XAUUSD) → documented; generalise later.
- Live gaps (no trade history) → honest "n/a", never 0-as-fact.
- Positions with no SL → excluded from open-risk (not `|entry−0|`).
- Scope creep into the full signal→execution loop → `sizing` built but not wired.

## Acceptance Criteria

See `phase-06-risk-prop-firm.md`.

## Implementation Checklist

1. [x] `policy`, `types`, `open-risk` (+ tests).
2. [x] `gates` (+ tests).
3. [x] `evaluate` (+ tests).
4. [x] `sizing` (+ tests).
5. [x] Nullable counts (domain + read model + panel "n/a").
6. [x] `toRiskStatusReadModel` (+ test).
7. [x] Wire mock + live.
8. [x] Verify lint / source tsc / build / test.
9. [x] ADR 0008, risk engine doc, phase files, brain.
