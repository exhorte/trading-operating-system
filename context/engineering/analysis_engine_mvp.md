# ICT/SMC Analysis Engine MVP (v0.1)

Home: `lib/analysis/`. Consumes `Candle[]`, emits the canonical
`MarketContextState` (`lib/domain/analysis.ts`). Pure and transport-agnostic —
imports only `lib/domain`. Decision recorded in ADR 0006; vocabulary source is
`context/domain/ict_smc_framework.md`.

> Everything here is a **hypothesis, not a validated edge**. The engine is
> version `v0.1`; weights and tolerances are placeholders.

## Pipeline

```text
Candle[]
  → detectSwings            (fractal pivots)
  → detectStructureShifts   (BOS / CHOCH) → structuralBias
  → detectLiquidity         (equal highs/lows, PDH/PDL, swept flags)
  → detectFairValueGaps     (3-candle imbalance, fill/mitigation)
  → detectOrderBlocks       (last opposing candle before a shift)
  → sessionForTimestamp     (ICT session bucket)
  → priceLocationOf         (premium / discount / equilibrium)
  → scoreContext            (weighted confluence + breakdown)
  → MarketContextState
```

`analyzeMarketContext(input)` composes all stages. Public surface is
`lib/analysis/index.ts`.

## In scope (MVP)

| Engine (from framework doc) | MVP implementation |
| --- | --- |
| Swing | strict fractal highs/lows, `swingLookback` bars each side |
| Market Structure | BOS (continuation) and CHOCH (first counter-trend break) |
| Liquidity | equal highs/lows (within tolerance), previous-day high/low, swept flag |
| PD Array | fair value gaps (+ fill % and mitigation), basic order blocks |
| Session | timestamp → ICT session via configured UTC windows |
| Bias | follows market structure |
| Premium/Discount | location of price inside the latest swing range |
| Scoring | weighted `ScoreComponent[]` → `score` / `maxScore` |

## Deferred (not in v0.1)

- SMT / cross-asset divergence (Gold/DXY, Gold/Silver, …)
- News & macro engine (NFP, CPI, FOMC gating)
- Premium/discount **OTE** zones, consequent encroachment, 50% equilibrium entries
- Breaker / mitigation / rejection blocks, inverse FVG, volume imbalance
- Entry-sequence engine (sweep → displacement → FVG/OB → retracement → trigger)
- Trade-management engine (SL/TP/BE/trailing/partials)

Bias and Scoring are the extension points: new engines add components without
reshaping the pipeline.

## Invariants

- **No look-ahead.** A bar's state uses only candles up to that bar. Swings
  confirm `lookback` bars after they form; sweep and mitigation scans move
  forward only. Asserted in tests.
- **Purity.** `lib/analysis` imports only `lib/domain`. The domain→read-model
  projection lives in `lib/contracts/projections.ts`, never inside the engine.
- **Determinism.** Same candles + same config → same `MarketContextState`.

## Config knobs (`config.ts`)

`swingLookback`, `equalLevelTolerance`, `minFvgSize`, `structureSwingWindow`,
`sessionWindows`, and `scoreWeights`. Tolerances are raw price units in v0.1; a
later revision should derive them from ATR / symbol `tickSize`.

## Consumption

The mock cockpit feeds a deterministic synthetic series (`lib/mock/candles.ts`)
through the engine and `toMarketContextReadModel`, so the Market Context panel
renders computed output while staying MOCK-badged. A future MT5/market-data feed
replaces the synthetic candles with no engine change.

## Testing

Vitest, `npm test`. Each detector has deterministic-fixture unit tests plus an
orchestrator integration test and a projection test (`lib/**/*.test.ts`). See
`context/engineering/testing_strategy.md`.
