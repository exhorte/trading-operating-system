# Phase 13 — Execution Realism & Virgin Holdout

Status: **implemented 2026-07-18** per the user's validated decisions (exact
bounds, frozen cost profile, pre-registered bar, verdict-mode requirements).
**The verdict run has NOT been launched** — user rule: review of hashes,
bounds, cost profile, and pass bar first. Prerequisites: Phase 12 closed with
the frozen candidate `CANDIDATE_CONFIG_2026_07_18`. Standing rules: old OOS
never unlocked; no new filters on the consumed dataset; no paper trading
before the holdout verdict AND net metrics.

## User decisions of 2026-07-18 (all implemented)

1. **Holdout bounds (exact, no overlap)**: from **2024-06-01T00:00:00Z**
   inclusive to **2025-06-06T13:30:00Z exclusive** — verified against the DB:
   the dev set's first candle opens exactly at the exclusive bound.
2. **Frozen cost profile** (`FROZEN_COST_PROFILE_2026_07_18`):
   commission 0/side · slippage 0.05/leg · spread = max(floor 0.20, observed
   p95) = **0.26 persisted literally**. **Calibration caveat for review**: the
   stored ticks hold ZERO NY AM observations — the only observed window is
   London 2026-07-12 09:26→10:20 UTC (n=3,158, constant 0.26 = p50 = p95 =
   p99). Using the 0.20 floor when 0.26 was observed would be
   anti-conservative, hence 0.26. To recalibrate on true NY AM data, run the
   observer 12:00–16:00 UTC BEFORE the verdict, then re-freeze.
   Stress (informative only): spread max(0.30, p99 0.26) = 0.30, slippage
   0.10/leg. **Swap invariant**: profile has `swap: null` → the verdict
   REFUSES itself if any trade crosses a 21:00 or 22:00 UTC rollover
   (both plausible server midnights probed), with no metric computed — the
   holdout stays virgin on refusal. Providing Exness swap rates + rollover
   hour, re-freezing, and committing enables the retry.
3. **Pre-registered bar** (`VERDICT_CRITERIA_2026_07_18`, verbatim where
   quantified): PASS = n≥100 ∧ netExp≥+0.05R ∧ netCum>0 ∧ BUY/SELL n≥30 ∧ no
   side ≤ −0.10R ∧ no month >50% of net cum ∧ bootstrap p2.5 > −0.05R ∧ no
   omitted cost/swap. FAIL-first precedence (a fragile positive with a FAIL
   condition is FAIL, not INCONCLUSIVE). Operationalizations flagged for
   review: "interval too wide" = width > 0.40R (at expected n≈300-400 a
   normal-variance CI is ~0.29R; n=150 alone breaches it); month share only
   defined for a positive total; side rules apply at n≥30; bootstrap =
   10,000 seeded iterations (seed 20260718 → bit-reproducible).
4. **Verdict mode** (`--verdict-holdout`): rejects every override flag ·
   refuses a dirty tree (records commit hash) · single read enforced by the
   `holdout_verdicts` PRIMARY KEY, not just code · records commit/dataset/
   candidate/cost-profile sha256 hashes · zero metric output before the final
   block · attempts audited in `holdout_attempts` (technical failure before
   the verdict row exists → audited retry; row exists → consumed forever).
   All guards behaviorally verified (override rejection, dirty-tree refusal,
   ordinary-path clip inert on dev data).

## Review checklist before the verdict run (user)

- [ ] Bounds in `lib/backtest/holdout.ts` (2024-06-01 → 2025-06-06T13:30 excl.)
- [ ] Cost profile 0.26/0.05/0 + provenance (or collect NY AM ticks and re-freeze)
- [ ] Swap: provide Exness rates + rollover hour, or accept refusal-on-crossing
- [ ] Bar operationalizations (width 0.40R, FAIL precedence, month rule)
- [ ] Then: import anterior history → commit → `npx tsx scripts/backtest.ts --verdict-holdout`

---

## Original design (for the record)

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
