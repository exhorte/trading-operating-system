# Phase 13 — Execution Realism & Virgin Holdout (design)

Status: **design — awaiting user validation. No code written.**
Date: 2026-07-18. Prerequisites: Phase 12 closed with the frozen candidate
`CANDIDATE_CONFIG_2026_07_18` (trigger, NY AM only, 2R, middle confirmation,
structural stop + 0.5 ATR). Standing rules: old OOS never unlocked; no new
filters on the consumed 2025-06→2026-07 dataset; no paper trading before the
holdout verdict AND net-of-costs metrics.

## Objective

Give the frozen candidate its one remaining test: a **chronological holdout
never consulted by anyone or anything**, read **once**, with **conservative
net-of-costs metrics** alongside gross. This phase changes the measurement,
never the strategy — the candidate is immutable by definition.

## Part A — the virgin holdout

### Definition (declared now, before any data is touched)

- **Primary: anterior window `2024-06-01T00:00Z → 2025-06-06T00:00Z`**
  (XAUUSDm M15, ~12 months). This data was **never imported** — the current
  dataset starts 2025-06-06 — so no run, report, chart, or human eye has seen
  it. Declaring the boundary leaks nothing.
- **Complement: forward holdout** — candles after 2026-07-14 accumulate
  unconsulted for a later second verdict (the strongest possible test, and the
  antidote to the regime caveat below).
- The old OOS (2026-04-25 → 2026-07-14) is **retired**: never unlocked,
  never used. It is not the holdout.

### Expected n

Iteration 2 produced 346 non-OOS trades over ~10.5 consumed months (NY AM
only). Twelve anterior months should yield **~300–400 trades** — comfortably
powered for a verdict read.

### Regime caveat (stated a priori, part of the honest read)

2024-06 → 2025-06 contains a strong gold bull regime. A bias-following
strategy can look good there for regime reasons rather than edge reasons. The
verdict read must therefore look at BUY and SELL expectancies separately (both
already in the report), and the forward holdout remains the cleaner test.
This caveat is recorded **before** the number exists so it can't become a
post-hoc excuse in either direction.

### Tooling lock (the leak lessons applied BEFORE the data exists)

New `lib/backtest/holdout.ts` (pure, tested):

```ts
export const VIRGIN_HOLDOUT = {
  symbol: "XAUUSDm", timeframe: "M15",
  from: "2024-06-01T00:00:00.000Z", to: "2025-06-06T00:00:00.000Z",
} as const;
```

- `scripts/backtest.ts` (default): if the effective candle range overlaps the
  holdout window, **clip it out and warn loudly**; refuse to run if the
  requested range lies entirely inside. Exploration of the holdout is
  impossible by construction, not by discipline.
- `--verdict-holdout` (the single verdict mode): runs **exactly** the holdout
  window with **exactly** `CANDIDATE_CONFIG_2026_07_18` — every strategy
  override flag (`--sessions`, `--strategy`, `--every`) is rejected in this
  mode. Cost config is stamped into the run's config JSON. No splits — the
  whole window is one segment tagged `holdout`.
- Importing anterior candles is safe (a candle import reveals no performance)
  and can happen any time after design validation.
- Display surfaces: a `holdout` run only exists once the verdict is taken, so
  the report and `/backtests` may render it fully. Nothing needs hiding —
  by the time the row exists, the read has happened. What must never exist is
  a *non-verdict* run over holdout candles, and the clip rule guarantees that.

### Verdict protocol (one shot)

1. Import anterior history (`import_history.py` — read-only, safe).
2. **One** run: `npx tsx scripts/backtest.ts --verdict-holdout`.
3. Read once: gross AND net, whole window, BUY/SELL split noted.
4. Whatever the numbers: **no tuning against the holdout**. Pass → the paper-
   trading discussion opens (with the forward holdout still accumulating).
   Fail → the candidate dies; iteration resumes on the consumed dataset only,
   and the burned holdout is retired like the old OOS.

**Pre-registered pass bar (to fix with the user before the run)** — proposal:
net expectancy > 0 over the full holdout with n ≥ 100, and neither side
(BUY/SELL) catastrophically negative. To confirm or amend at design
validation, not after the read.

## Part B — conservative cost model, separate by construction

### Principle

Costs are a **post-processing layer** (`lib/backtest/costs.ts`, pure, tested).
The outcome simulation (binary SL/TP, conservative both-touch, timeout at
horizon close) is **unchanged**, so every gross number stays comparable with
every previous run. Each trade gets `costR` and `netR = grossR − costR`.

### Model

Per round trip, in price units, all adverse:

```text
costPrice = spreadPoints + 2 × slippagePointsPerLeg + commissionUsdPerLotRT / contractSize
costR     = costPrice / |entry − stop|          (volume cancels out)
```

- **spread** — candles are bid-quoted; a buy fills at ask. One full spread per
  round trip, conservative.
- **slippage** — fixed adverse points on each leg; TP fills get no favorable
  slippage (conservative asymmetry).
- **commission** — per-lot round trip in USD, converted through
  `contractSize` (100 oz); volume-independent in R terms.
- **tickSize/rounding** — levels already round to 0.01 (= XAUUSDm tick) in the
  strategy; the cost layer asserts it and documents it.
- **timeout exits** — market close exit: full round-trip cost applies, same as
  any exit.

### Parameters — fixed BEFORE the verdict run, never after

| parameter | proposed default | source |
| --- | --- | --- |
| `spreadPoints` | **0.20** | conservative for XAUUSDm standard; to calibrate against the stored live ticks (p75 of observed spread) and the user's terminal — whichever is WORSE |
| `slippagePointsPerLeg` | **0.05** | conservative constant; no historical fill data exists |
| `commissionUsdPerLotRT` | **0** (spread-only account) | user confirms their Exness account type; set if commission-based |
| `contractSize` | 100 | XAUUSD spec |

Calibration uses only cost inputs (spreads), never performance — it cannot
leak. Once the verdict run exists, these numbers are frozen with it.

### Honest limits (documented in the report banner)

The post-processing model ignores spread's effect on the *trigger levels
themselves* (a bid-quoted SL touch vs ask-quoted entry asymmetry) and uses a
constant spread with no historical series. The conservative constants are the
compensation. Net numbers are stated as approximations that bound realism from
below, not as account simulation — that remains deferred, as before.

### Persistence & display

- `backtest_trades` += `cost_r`, `net_r_multiple` (additive idempotent schema,
  same pattern as `features`/`split`).
- Run config JSON records the cost config used.
- Report and `/backtests`: gross headline AND net headline side by side; the
  per-dimension tables stay gross (cross-run comparability), with a compact
  net summary per split. Old runs without cost columns render gross-only with
  a note.

## Not in scope

Strategy changes of any kind; account-level simulation (lockouts, overlapping
positions, equity curve); historical spread series; paper trading (gated on
the verdict + net metrics); unlocking the old OOS (never).

## Checklist (after design validation)

1. `lib/backtest/holdout.ts` + clip/refuse logic in the runner + tests
   (overlap clip, full-inside refusal, verdict mode rejecting overrides).
2. `lib/backtest/costs.ts` + tests (cost math, volume independence, timeout
   treatment) + schema additions + runner wiring (gross AND net persisted).
3. Report + `/backtests` net display (+ gross-only fallback on old runs).
4. Spread calibration from stored ticks → fix parameters with the user.
5. Import anterior history; gates (lint, tsc, Vitest, dotnet).
6. **Fix the pass bar with the user** → the single `--verdict-holdout` run →
   record the verdict in the brain, whatever it says.
