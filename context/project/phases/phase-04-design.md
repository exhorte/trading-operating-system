# Phase 04 Design - ICT/SMC Engine MVP

Status: validated by the user on 2026-07-08 (three decisions confirmed: build the ICT/SMC engine as Phase 04; engine home = TypeScript in this repo; MVP scope as listed) and implemented the same day. Completion notes in `phase-04-ict-smc-engine.md`.

## Objective

Build the first server-side analysis engine in TypeScript: consume `Candle[]` and emit a canonical `MarketContextState` (already defined in `lib/domain/analysis.ts`). Turn the cockpit's currently-fabricated Market Context panel into computed output, touching zero UI code and staying MOCK-badged. Bounded MVP subset of the ~15 engines in `ict_smc_framework.md`.

## Existing Context

- Output type exists: `MarketContextState` with embedded `StructureShift`/`LiquidityLevel`/`FairValueGap`/`OrderBlock`/`ScoreComponent`. Input type exists: `Candle`.
- Read model ≠ domain model: the panel renders `MarketContext` (flattened strings) from `lib/contracts/snapshots.ts`. A projection must bridge domain → read model.
- Dependency law (ADR 0004): `components → lib/realtime → lib/contracts → lib/domain`; domain imports nothing. The engine is pure and imports only `lib/domain`.
- `testing_strategy.md` already prescribes unit-tested ICT detectors + deterministic candle fixtures; no test runner existed yet.

## Impact Analysis

- New pure layer `lib/analysis/` at the bottom next to `lib/domain`. Transport-agnostic; re-implementable in .NET (consistent with ADR 0004).
- One new projection `lib/contracts/projections.ts` (`MarketContextState → MarketContext`), allowed to import both layers.
- Mock rewiring, not UI change: `mockMarketContext()` becomes `project(analyze(candles))`; panel, seam, store, and event contract untouched.
- First new dependency since Phase 01: dev-only Vitest + `test` script. Runtime deps stay zero. No backend/gateway/execution impact; not blocked by the deferred ASP.NET Core work.

## Proposed Architecture

Small single-responsibility pure modules composed by one orchestrator: `config`, `types`, `swings`, `structure`, `liquidity`, `pd-arrays`, `sessions`, `bias`, `scoring`, `market-context`, `index`.

No-look-ahead invariant: each detector evaluates bar `i` using only candles `0…i`; swings confirm `lookback` bars late; sweep/mitigation scans move forward only. Engine tagged `v0.1`, treated as a hypothesis.

## Data Flow

```text
Candle[] (synthetic mock fixture, later MT5 candles)
  → analyzeMarketContext()  (swings→structure→liquidity→pd-arrays→sessions→bias→scoring)
  → MarketContextState
  → toMarketContextReadModel()  (lib/contracts/projections.ts)
  → MarketContext read model
  → analysis.market_context.updated → CockpitStore → MarketContextPanel (unchanged)
```

## Files To Create Or Modify

Create: `lib/analysis/*` (+ `*.test.ts`, `test-helpers.ts`), `lib/contracts/projections.ts` (+ test), `lib/mock/candles.ts`, `vitest.config.ts`, `context/engineering/analysis_engine_mvp.md`, `context/adr/0006-ict-smc-engine-typescript.md`, this design doc, `phase-04-ict-smc-engine.md`.

Modify: `package.json` (Vitest dev dep + `test` script), `lib/mock/initial-snapshot.ts` (`mockMarketContext` computes), `lib/realtime/mock-client.ts` (engine-driven `emitContextUpdate`), `context/project/{project_state,handoff,changelog,roadmap}.md`.

## Risks

- Presenting heuristics as truth — mitigated by `v0.1` label, MOCK badge, no profitability claims, detection-only test assertions.
- Scope creep into all engines — hard MVP boundary; deferred list in the engine doc.
- Dependency-direction violation — engine imports only `lib/domain`; projection isolated in `lib/contracts`.
- Look-ahead bias — `0…i`-only rule asserted in tests.
- New dependency — Vitest is dev-only and mandated by `testing_strategy.md`.

## Acceptance Criteria

See `phase-04-ict-smc-engine.md`.

## Implementation Checklist

1. [x] Vitest + `test` script + `vitest.config.ts`; smoke green.
2. [x] `config.ts`, `types.ts`.
3. [x] `swings.ts` + tests → `structure.ts` + tests.
4. [x] `pd-arrays.ts` (FVG, OB) + tests → `liquidity.ts` + tests.
5. [x] `sessions.ts`, `bias.ts`, `scoring.ts` + tests.
6. [x] `market-context.ts` orchestrator + integration test.
7. [x] `lib/contracts/projections.ts` + test.
8. [x] `lib/mock/candles.ts`; rewire `mockMarketContext()`; engine-driven `emitContextUpdate()`.
9. [x] Verify lint / typecheck / build / test.
10. [x] ADR 0006, engine MVP doc, phase files, project-brain updates.
