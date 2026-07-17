# Phase 12 Part B — Iteration 1: a real entry trigger

Status: **implemented 2026-07-17** (pure code + tests + runner/reporter wiring; gates green). **The train/validation backtest run is the user's step — it needs Docker + the TimescaleDB container, which were down at implementation time.** Discipline: `context/backtesting/diagnostics_workflow.md`, ADR 0013.

## Implementation (done)

- `lib/analysis/atr.ts` — Wilder ATR, pure, `lib/domain` only; does not touch `MarketContextState` or the score. + `atr.test.ts` (4). Exported from the analysis barrel.
- `lib/strategy/` — new pure engine (imports only `lib/domain` + `lib/analysis`): `config.ts` (knobs, all fixed a priori), `trigger.ts` (`evaluateTrigger`, stateless), `index.ts`. + `trigger.test.ts` (11): happy path, every gate rejecting on its own, first-retest-only, confirmation modes, expiry, neutral bias, and the no-look-ahead invariant.
- `scripts/backtest.ts` — `--strategy sampler|trigger`; trigger defaults `--every` to 1; `engine_version` and run `config.strategy` record the arm; **the sampler path is byte-for-byte unchanged** (control arm stays reproducible).
- `lib/backtest/segments.ts` — `stopDistance` now range-buckets (`<3 / 3-5 / 5-7 / 7-10 / 10+`) since the trigger's stop is continuous.
- **Confirmation-close decision: `middle`, fixed a priori** (see resolved open question below).
- Gates: lint clean, `tsc --noEmit` exit 0, **86 Vitest** (15 new).
- **Behavioral smoke test** (scratchpad, no DB): walking the real analysis engine + trigger over 2,668 bars of a noisy synthetic random walk fired **90 signals (3.4% of bars)**, balanced buy/sell, all with correct 2R geometry and score passed through. Proves the wiring emits well-formed signals, the first-retest gate holds (not every bar), and the setup is reachable (not zero). Synthetic data — indicative of firing rate only, says nothing about edge.

---

## Original design (below) — for the record

## Experimental objective

**One question only: does a real entry condition beat a periodic sampler?**

The de-confounded baseline says the stub does not generalize (train ~neutral, validation negative) and that no single dimension — side, sideVsBias, score, stopDistance, BOS/CHOCH, day, session — carries a stable enough effect to justify a filter. The one robust finding is the concentration of losses in the first 1–2 bars. A strategy that fires every 8 bars with no setup and a fixed noise-width stop samples arbitrary moments; that is the structural cause, and filtering a sampler is selection on noise.

So iteration 1 replaces the *entry condition*, and nothing else.

**Explicitly NOT changed** (user constraint — any of these moving would confound the comparison): the score and its weights, session windows, day filters, the Risk Engine and its gates, the 2R target, and the analysis detector config.

## The hypothesis

At bar `i`, emit at most one signal when **all** hold:

1. **Directional bias** — `context.bias` is bullish or bearish (neutral never trades). Side = bias direction. No counter-bias probes.
2. **Fresh structure shift** — `context.lastStructureShift` exists, `direction === bias`, and `occurredAt` is within `maxShiftAgeBars`.
3. **Fresh FVG created by the displacement** — an active FVG with `direction === bias` and `detectedAt > shift.occurredAt`, formed within `maxSetupAgeBars`.
4. **First retest** — no bar from the FVG's formation+1 through `i-1` touches its zone, and bar `i` does.
5. **Confirmation close** — bar `i` closes in the bias direction *and* closes on the correct side of the gap (the gap held).
6. **One signal per setup** — implied by (4): only one bar can be the first touch. No dedup state needed.
7. **Setup expiry** — enforced by the age caps in (2) and (3).

Entry `= candles[i].close` (existing convention: the outcome simulates from `i+1`, so no-look-ahead holds). Stop `=` structural invalidation — beyond the FVG's far edge — offset by an ATR buffer floored at a tick minimum. Target `=` entry ± 2R (**unchanged**).

## Architecture

**New pure module `lib/strategy/`**, imports only `lib/domain` (ADR 0006 law, same as `lib/analysis` and `lib/risk`). Ports to .NET later like its siblings.

`lib/mock/signals.ts` **stays** as the periodic sampler: it is the experiment's **control arm** and it still drives the cockpit's mock/live signal flow. Do not delete or "improve" it during this iteration.

### Stateless by construction — this is load-bearing

The trigger is a pure function of `(window, context) → StrategySignal | null`, evaluated per bar. "First retest" and "one signal per setup" are **derived from the window**, never tracked in mutable state. Three reasons, one of them a trap found in the code:

- **`fvgId` is not stable across bars.** `finalizeGap` emits `fvg-${formedAt}` where `formedAt` is an index into the rolling 300-bar window ([`pd-arrays.ts:77`](../../../lib/analysis/pd-arrays.ts)). As the window slides, the same gap silently changes id and different gaps reuse ids. **Any state keyed by `fvgId` would corrupt.**
- No-look-ahead stays trivially provable: the function only ever reads bars ≤ `i`.
- Backtest and live behave identically — there is no state to rebuild on reconnect, and no replay divergence.

### The context alone is insufficient — the trigger must scan the window

`analyzeMarketContext` filters `activeFairValueGaps` to `mitigatedAt === null`, i.e. it only drops gaps filled **100%** ([`market-context.ts:93`](../../../lib/analysis/market-context.ts)), and `filledPercent` is computed forward to the *last* candle of the window. At bar `i` a partially-filled gap therefore looks identical whether it was first touched at `i` or at `i-5`. Condition (4) cannot be evaluated from `MarketContextState`.

So the trigger takes the candle window as input and runs its own touch scan from the gap's formation index. This is why `lib/strategy` receives `(window, context)` rather than context alone.

### New: ATR

No ATR exists anywhere in the repo today. Add `lib/analysis/atr.ts` (pure, `lib/domain` only) — a standard Wilder ATR over the window. It adds a helper only; `MarketContextState` and the score are untouched, so the constraint above holds.

## Knobs — fixed a priori, NOT tuned in this iteration

Every knob is a degree of freedom and therefore an overfitting surface. These are set once, by convention, before seeing any result. **Tuning any of them is a separate future iteration, one at a time.**

| knob | value | rationale |
| --- | --- | --- |
| `maxShiftAgeBars` | 12 | ~3h on M15; the displacement must still be relevant |
| `maxSetupAgeBars` | 12 | gap goes stale; bounds the setup's life |
| `atrPeriod` | 14 | the standard, chosen to avoid a free parameter |
| `atrBufferMultiple` | 0.5 | half an ATR beyond structural invalidation |
| `minStopTicks` | tickSize floor | prevents a degenerate stop in dead volatility |
| target | 2R | **unchanged by constraint** |

## Runner changes

- **`--every` must be 1 for the trigger.** A retest can land on any bar; sampling every 8 would miss ~7/8 of setups. `--every 8` was a sampler affordance and is meaningless here.
- **`--strategy sampler|trigger`** so the control arm stays reproducible and both arms come from one code path.
- **`ENGINE_VERSION`** must change (→ `ict-smc v0.1 / risk v0.1 / trigger-strategy v0.1`); the run record must never be ambiguous about which arm produced it.
- **Perf**: every-bar evaluation is ~8× more `analyzeMarketContext` calls, each O(gaps × window) on a 300-bar window. Expect minutes, not seconds. Acceptable; optimize only if it actually hurts.

## Consequences for the diagnostics

- **`sideVsBias` collapses to `with` only** — there are no probes. The dimension becomes constant and uninformative for this arm. Expected, not a bug.
- **`stopDistance` becomes continuous** (ATR-derived). The bucketer I just changed to report the measured distance (`toFixed(1)`) would explode into dozens of near-empty buckets. **It needs range bucketing for the trigger arm** — a small reporter change to make before reading iteration 1.
- Trade counts drop sharply. See the power risk below.

## The main risk: statistical power — pre-registered

A strict trigger produces far fewer signals than a sampler firing every 8 bars. If the **validation** arm lands under `MIN_BUCKET_N` (30 trades), the comparison is **not actionable**.

This must be decided now, before the number exists, because the temptation afterwards is obvious and corrupting: loosening the trigger until n is large enough is overfitting by another route — it just moves the search from filters to the trigger's own knobs.

**Pre-commitment:**

- If validation n ≥ 30 → read the comparison and decide.
- If validation n < 30 → the result is **underpowered and inconclusive**. We do **not** loosen the trigger to chase n. The options are: extend the candle history (more months), or accept the inconclusive verdict and record it.
- Either way, OOS stays locked.

## Comparison protocol

- **Control**: the de-confounded sampler run (already in hand).
- **Treatment**: the trigger run, same symbol/timeframe/period.
- **Primary metric**: expectancy R on train, then validation.
- **Secondary, and the actual target of the intervention**: the share of losses in the 1–2 bar duration bucket. The trigger is meant to attack precisely this; if the concentration does not fall, the mechanism did not work even if expectancy moved.
- **Ships only if** it improves on train **and** holds on validation (rule 2). OOS read once, at the end of the campaign — never here.
- Honest bar: two arms with very different n means comparing two noisy estimates. A small expectancy delta is not evidence.

## Checklist (implementation, after validation)

1. `lib/analysis/atr.ts` + tests (pure).
2. `lib/strategy/types.ts`, `config.ts` (knobs above), `trigger.ts` (the pure trigger), `index.ts`.
3. Tests, deterministic fixtures — must cover: fresh-shift gate, FVG-after-displacement gate, **first retest only** (a second touch must NOT signal), confirmation-close gate, expiry, neutral bias → null, and an explicit **no-look-ahead assertion** (the signal at bar `i` is unchanged when future bars are appended).
4. Reporter: range bucketing for continuous `stopDistance`.
5. Runner: `--strategy`, `--every 1` default for trigger, `ENGINE_VERSION`.
6. Gates: lint, `tsc --noEmit`, Vitest.
7. Run train → compare → validation. Record run ids in the brain.

## Resolved: confirmation close = middle

Fixed a priori to **middle** — closes in the bias direction **and** holds the gap (`close > fvg.low` for a buy). All three modes are implemented (`ConfirmationClose` in `config.ts`) so a *future* iteration can test lenient/strict as its own single hypothesis; this iteration does not tune it. lenient = direction only; strict = closes fully beyond the gap.
