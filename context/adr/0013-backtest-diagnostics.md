# ADR 0013 - Backtest Diagnostics: Feature Capture, Chronological Splits, Locked OOS

## Status

Accepted

## Context

Phase 11's baseline said "no edge" (−0.02R over 1,261 trades) but not WHERE the losses come from: `backtest_trades` didn't store the signal's market context, and the 1,948 rejections weren't recorded at all. The user specified Phase 12 as diagnose-before-changing-rules, with segmented analyses over 13 dimensions and a train/validation/out-of-sample discipline against overfitting.

## Decision

1. **Feature capture at signal time** — `backtest_trades.features jsonb`, frozen by the runner. Stable key set (the report depends on it): `session`, `bias`, `sideVsBias` (`with`|`counter`), `structure` (`bos`|`choch`|`none`), `stopDistance`, `scoreComponents` (label→score), `fvgAligned`/`fvgInside`, `obAligned`/`obInside`, `liqKinds` (string[]). Day-of-week/month derive from `signal_time`. The stub's planned RR is constant (2.0) by construction, so RR segmentation is replaced by stop-distance buckets — stated in the report.
2. **Rejections table** — `backtest_rejections` (seq, time, side, score, session, reason, split): the "risk gates" dimension is analyzed on refusals, since approved trades had open gates by definition.
3. **Chronological 60/20/20 splits**, time-based (not trade-count-based, so trade density can't leak), boundaries stored in the run config, every trade/rejection tagged. Refinement decisions are made on TRAIN, confirmed on VALIDATION.
4. **OOS is locked by tooling**: `backtest-report.ts` hides the OOS split unless `--unlock-oos` is passed — to be used ONCE at the end of the refinement campaign. Reading it earlier turns it into a second validation set.
   - **Hiding the split's tables is not enough — no AGGREGATE may include OOS either** (added 2026-07-17, after the lock leaked for three runs; see below). Any headline computed over "all trades" silently reveals out-of-sample performance. The `backtest_runs` row stores whole-period metrics **by design** (it is the record read at unlock), so **no display surface may render that row's `win_rate` / `expectancy_r` / `cumulative_r` while the campaign is live**. Aggregates are built from `reportableTrades(trades, unlockOos)` + `summarize()` in `lib/backtest/segments.ts` (pure, regression-tested).
5. **Report** — `scripts/backtest-report.ts <runId>`: rejection breakdown + per-dimension tables (worst buckets first — it's a loss hunt) per split, console + `backtest-reports/<runId>.md` (gitignored artifact). Buckets with n < 30 are flagged `⚠ low n`; with 13+ dimensions, only strong, explainable, train+validation-consistent effects may drive changes.
6. Pure aggregation in `lib/backtest/segments.ts` (tested); the runner gained `--from/--to` so refinement iterations can run on the train window only.

7. **Strategy variety knobs must be orthogonal factors** (added 2026-07-17 — see the retraction below). Any deliberate variation the strategy injects for diagnostic purposes has to cycle on a modulus coprime with every other knob's, so the segmented report can attribute an effect to one factor. Two knobs on the same modulus produce perfectly aliased cohorts that no amount of split discipline can disentangle. A strategy must never doctor a value the diagnostics treat as an engine output (e.g. `score`).

## First findings (enriched baseline `bt-mrkz8r44-d57578d8`, deterministic re-run of the Phase 11 baseline)

**⚠ Partially retracted 2026-07-17 — the baseline stub was confounded.** `mockStrategySignal` keyed three variety knobs off the same counter: `counterBias = seq % 4 === 0`, `stopDistance = 3.5 + (seq % 4) * 1.5`, and a `−3` score penalty applied only to counter-bias probes. Counter-bias trades were therefore *exactly* the 3.5-stop trades, with an artificially docked score — one cohort wearing three labels. The report proves the aliasing: `sideVsBias=counter` and `stopDistance=3.5` are identical in every split (train n=189 / −0.19R / −36R cum; validation n=63 / −0.14R / −9R cum). Findings below are re-graded accordingly; the stub was orthogonalized in Phase 12 Part B (`seq % 4` for side, `seq % 3` for stop 4.0→8.0, undoctored score) and the baseline must be re-run before any of this is trusted.

- **Survives the confound** — score 6 is the only bucket positive in both splits (train +0.15R / n=299; val +0.03R / n=105). A probe could only reach score 6 from a rare context score of 9 (n=15), so this bucket is nearly pure with-bias: the engine's confluence measure is directionally informative.
- **Survives, and is the real signal** — 1–2-bar losses dominate (train −0.34R / n=316; val −0.23R / n=188). Diagnostic, not a filter: entries die immediately. Root cause is structural — the stub fires every 8 bars with no entry trigger and a fixed noise-width stop, i.e. it samples arbitrary moments. −0.02R is a random sampler behaving like one.
- **Not attributable** — "counter-bias probes bleed" and "the 3.5 stop bleeds" are the same 189/63 trades. Consistent across splits, but the cause could be the counter-trend side, the tightest stop, the docked score, or any mix.
- **Contaminated** — "low scores bleed" (score 3: −0.23R / −0.49R). Score-3 trades are largely probes docked from context score 6, so the score dimension carried the probe flag.
- **Train-only mirages killed by validation** (would have been overfit without the split): side (buy>sell reverses), structure (BOS>CHOCH reverses), session (NY edge vanishes), bias direction. **`stopDistance` no longer belongs on this list**: the 6.5 bucket did flip, but 3.5 was consistently worst in both splits because it was the probe cohort in disguise.
- Rejections: 100% session-filter refusals (Asia/NY-PM/off-session) — gates behaved as configured; no risk-gate anomaly.

## OOS lock leak (found + fixed 2026-07-17)

The lock hid the OOS *tables* but three surfaces still displayed whole-period aggregates that included the 254 OOS trades:

1. `backtest-report.ts` — the headline (`1,261 trades / +9.1R`), read straight off the `backtest_runs` row. **Found by the user.**
2. `scripts/backtest.ts` — the runner's final console summary, printed on **every** run with no `--unlock-oos` concept at all. The worse leak: visible before the report is even opened.
3. `/backtests` (`backtests-workspace.tsx` → `BacktestRepository` → `/api/backtests`) — renders the run row permanently. **Still open — needs a decision (see Consequences).**

Fixed 1 and 2; the guard now lives in pure tested code (`reportableTrades` + `summarize`) rather than in scripts, so the leak cannot silently return.

**Lesson**: a lock enforced at the *display* layer must cover every derived figure, not just the obvious one. "Hide the section" is not "withhold the information". The numbers that leaked cannot be unseen — Part B's iteration 1 was therefore designed without reference to them.

## Consequences

- Rule changes are now hypothesis-driven and survivable-by-validation, or they don't ship.
- **Open**: the `/backtests` page still shows OOS-inclusive run metrics. It is a product surface over a run archive, so it can't simply be blanked — decide between (a) rendering split-scoped metrics while a run's campaign is live, (b) a per-run `oos_unlocked` flag gating the aggregate, or (c) accepting the page as an unlock surface and documenting it. Until decided, **treat the page as leaking**.
- Split discipline catches effects that don't generalize across time; it does **not** catch a confounded experimental design. Auditing how the strategy generates its own variation is a prerequisite to reading any segmented report.
- Old (feature-less) runs remain readable; the report flags them and advises a re-run.
- Deferred still: costs, account-level simulation, paper trading — gated on an improved raw R distribution.
