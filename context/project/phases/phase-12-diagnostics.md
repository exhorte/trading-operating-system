# Phase 12 - Backtest Diagnostics & Strategy Refinement

Status: Part A (diagnostics tooling) implemented 2026-07-14 per the user's spec (design validated in-session: 60/20/20 chronological splits; console+markdown report; OOS locked by tooling). Part B (data-driven refinement iterations) started 2026-07-17 with a de-confounding fix.

## Objective

Identify precisely the sources of losses BEFORE modifying any rule, under an anti-overfitting discipline; then iterate the strategy/engine with the backtester as the measured feedback loop. Costs and paper trading stay gated on an improved raw R distribution.

## Part A — delivered

- Schema: `backtest_trades` += `features jsonb` + `split`; new `backtest_rejections` (the "risk gates" dimension lives on refusals).
- Runner v2: frozen feature capture (ADR 0013 key set), time-based 60/20/20 split tagging, rejection recording, `--from/--to` filters.
- `lib/backtest/segments.ts` (pure, tested): per-bucket metrics, worst-first, `⚠ low n` flag (<30).
- `scripts/backtest-report.ts`: rejections + 15 dimension tables × split, console + `backtest-reports/<runId>.md`; **OOS hidden unless `--unlock-oos`**.
- Enriched baseline re-run `bt-mrkz8r44-d57578d8`: **bit-identical metrics to the Phase 11 baseline** (32.31% / −0.02R / −21.55R) — the pipeline is deterministic; 1,948 rejections captured (100% session filter).

## First findings — partially retracted 2026-07-17

The Part A findings were read off a **confounded stub**. `mockStrategySignal` keyed three variety knobs off one counter — `counterBias = seq % 4 === 0`, `stopDistance = 3.5 + (seq % 4) * 1.5`, and a `−3` score penalty applied only to probes. Counter-bias trades were therefore *exactly* the 3.5-stop trades, carrying a docked score: one cohort, three labels. The report proves it — `sideVsBias=counter` and `stopDistance=3.5` are identical in every split (n=189 / −0.19R / −36R cum; n=63 / −0.14R / −9R cum).

Re-graded:

1. **Survives** — score 6 is the only bucket positive in both splits (+0.15R n=299 / +0.03R n=105). A probe could only land there from a rare context score of 9 (n=15), so the bucket is nearly pure with-bias: the engine's confluence measure is directionally informative.
2. **Survives, and is the real signal** — **1–2-bar losses dominate** (−0.34R n=316 / −0.23R n=188). The stub fires every 8 bars with **no entry trigger** and a fixed noise-width stop; it samples arbitrary moments, so −0.02R is a random sampler behaving like one. Entry timing / stop placement is the weak joint.
3. **Not attributable** — "counter-bias probes bleed" and "the 3.5 stop bleeds" are the same 189/63 trades. Consistent across splits, but the cause could be the counter-trend side, the tightest stop, the docked score, or any mix.
4. **Contaminated** — "low scores bleed" (score 3: −0.23R/−0.49R). Those trades are largely probes docked from context score 6, so the score dimension carried the probe flag.
5. **Train-only mirages** killed by validation: side, structure kind (BOS/CHOCH reversed), session, bias direction. **Stop distance leaves this list** — 6.5 did flip, but 3.5 was consistently worst in both splits because it was the probe cohort in disguise.

Rejections: 100% session filter, as configured (unaffected).

Lesson recorded in ADR 0013 (decision 7) and the workflow doc: splits catch effects that don't generalize across time; they do **not** catch an aliased design. Auditing how the strategy generates its own variation is a prerequisite to reading any segmented report.

## Part B — in progress (2026-07-17)

**Step 1 — de-confound (done, user-validated).** An experimental-design fix, not a strategy hypothesis: `stopDistance` now cycles on `seq % 3` (4.0/6.0/8.0) while `counterBias` stays on `seq % 4` — coprime, so all 12 (side, stop) combinations occur per period and effects become attributable. The strategy no longer doctors `score`; it passes the engine's context score through. `segments.ts` reports the measured stop distance instead of snapping to the old hardcoded 3.5/5.0/6.5/8.0 lattice.

**Step 2 — re-run the baseline and re-read** (needs Docker Desktop + the DB up; blocked at time of writing). The new run is NOT bit-comparable to `bt-mrkz8r44-d57578d8` — the stub changed by design. Keep the old run for the record.

**Step 3 — iteration 1**, chosen from the de-confounded report. Open strategic question to settle first: with 1–2-bar losses as the surviving finding, filter-tuning a trigger-less stub may be selecting on noise. Giving the strategy a real entry trigger (fresh structure shift + PD-array touch, ATR-derived stop) is the candidate that addresses the root cause; a minimum-score threshold is the incremental alternative. One hypothesis per iteration, train-first, validation-confirmed, OOS once at the end.

## Gates

Part A: lint clean · source tsc exit 0 · 69 Vitest (13 backtest) · dotnet build 0/0 + 20/20 · schema applied idempotently to the live DB.

Part B step 1: lint clean · `tsc --noEmit` exit 0 · 69 Vitest.
