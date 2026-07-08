# Phase 04 - ICT/SMC Engine MVP

Status: implemented 2026-07-08 (design in `phase-04-design.md`, validated by the user before implementation). Engine lives in TypeScript in this repo; Vitest introduced.

## Objective

Implement the first server-side analysis engine: consume `Candle[]` and emit a canonical `MarketContextState`, turning the cockpit's Market Context panel from hand-written mock into computed output — with zero UI/seam changes.

## Scope

In scope (v0.1): swings, market structure (BOS/CHOCH), liquidity (equal highs/lows, previous-day high/low, swept flags), PD arrays (fair value gaps + basic order blocks), session mapping, bias, premium/discount location, weighted scoring.

Deferred: SMT/divergence, news/macro, premium-discount OTE, breaker/mitigation/rejection blocks, entry-sequence and trade-management engines. See `context/engineering/analysis_engine_mvp.md`.

## Inputs

- `context/domain/ict_smc_framework.md` (vocabulary + target engines)
- `lib/domain/analysis.ts` (output type), `lib/domain/market.ts` (input type)
- `lib/contracts/snapshots.ts` (`MarketContext` read model)
- `context/engineering/testing_strategy.md`

## Acceptance Criteria

- `analyzeMarketContext(Candle[])` returns a valid `MarketContextState`, importing only `lib/domain`.
- Each detector implemented and unit-tested against deterministic fixtures; no-look-ahead asserted.
- `toMarketContextReadModel()` projection implemented and unit-tested.
- Market Context panel renders engine-computed output through the existing event/store path; MOCK badge present; no component/seam change.
- `npm run lint`, `tsc --noEmit`, `npm run build`, `npm test` all pass.
- ADR 0006 + engine MVP doc written; project brain updated.

## Implementation Notes (2026-07-08)

Built in `lib/analysis/`: `config`, `types`, `swings`, `structure`, `liquidity`, `pd-arrays`, `sessions`, `bias`, `scoring`, `market-context` (orchestrator), `index` (barrel), plus `test-helpers` and colocated `*.test.ts`. Projection added at `lib/contracts/projections.ts`. Deterministic fixture `lib/mock/candles.ts` (`mockCandles` seeded snapshot + `nextCandles` live advance); `mockMarketContext()` and the mock client's `emitContextUpdate()` now run the engine + projection instead of fabricating strings.

Verified: lint clean, `tsc --noEmit` exit 0, build passes (13 routes), 23 Vitest tests pass across 9 files. Runtime sanity on the mock series yields a coherent bullish context ("Uptrend after BOS", a bullish FVG + OB, PDL liquidity, score 5/10).

Engine is v0.1 — a hypothesis, not a validated edge. New dev dependency: Vitest (runtime deps still zero).

## Closure (2026-07-08)

Closed 2026-07-08 (committed `298480a`). Validated both ways: the mock cockpit renders engine-computed context, and in the Phase 05 live run the same engine produced a coherent context ("Downtrend after CHOCH", PDH, bearish FVG/OB, score 5/10) from the user's **real** XAUUSDm M15 candles. Gates green at closure: lint clean, source `tsc` exit 0, build (13 routes), 23→ (now 29) Vitest tests.
