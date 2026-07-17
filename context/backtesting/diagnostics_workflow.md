# Backtest Diagnostics & Refinement Workflow (Phase 12)

Discipline for turning the backtester into a refinement feedback loop WITHOUT
overfitting. Decision record: ADR 0013.

## The rules

1. **Diagnose before changing.** No rule/weight/detector change without a
   segmented report showing where the losses are.
2. **Splits are law.** Chronological 60/20/20 (train/validation/oos), tagged by
   the runner, boundaries in the run config.
   - Iterate on **TRAIN** (`--to <trainEnd>` for faster loops).
   - A change ships only if it also holds on **VALIDATION**.
   - **OOS is read ONCE**, at the end of the whole campaign
     (`backtest-report.ts <runId> --unlock-oos`). Never optimize against it.
   - **No aggregate may include OOS while locked.** Hiding the OOS tables is not
     enough: any "all trades" headline leaks it. The `backtest_runs` row holds
     whole-period metrics by design — never render its `win_rate` /
     `expectancy_r` / `cumulative_r` during a campaign. Build headlines from
     `reportableTrades()` + `summarize()`. (The lock leaked for three runs
     exactly this way; the `/backtests` page still does — treat it as leaking.)
3. **Multi-comparison guard.** 13+ dimensions × buckets will produce flukes.
   Act only on effects that are (a) strong, (b) mechanically explainable,
   (c) consistent across train AND validation, (d) not `⚠ low n` (<30 trades).
4. **Check for confounds before reading the report.** Splits catch effects that
   don't generalize across time; they do NOT catch an aliased design. Any
   variation the strategy injects must cycle on a modulus coprime with every
   other knob's, and the strategy must never doctor a value the diagnostics
   treat as an engine output. Two dimensions showing *identical* n / exp R / cum
   R are the same cohort under two names — attribute nothing to either.
   (Learned the hard way: see the Phase 12 retraction below.)
5. **One hypothesis per iteration**, recorded in the brain (what/why/expected
   effect), then measured. Keep the run ids; runs are cheap, amnesia is not.
6. Costs and paper trading stay out until the RAW R distribution improves.

## Commands

```powershell
# full run (enriched: features + splits + rejections)
npx tsx scripts/backtest.ts --symbol XAUUSDm --timeframe M15

# diagnostic report (train + validation; OOS locked)
npx tsx scripts/backtest-report.ts <runId>

# refinement iteration on the train window only
npx tsx scripts/backtest.ts --to <trainEnd from run config>

# END of campaign, once:
npx tsx scripts/backtest-report.ts <runId> --unlock-oos
```

Reports land in `backtest-reports/<runId>.md` (gitignored artifacts).

## Baseline findings (2026-07-14, run `bt-mrkz8r44-d57578d8`)

**⚠ Partially retracted 2026-07-17 — the stub was confounded; re-run required.**
`mockStrategySignal` keyed counter-bias (`seq % 4 === 0`), stop distance
(`3.5 + (seq % 4) * 1.5`) and a score penalty off one counter, so counter-bias
trades were *exactly* the 3.5-stop trades with a docked score. The report shows
the tell: `sideVsBias=counter` and `stopDistance=3.5` are identical in both
splits (n=189 / −0.19R / −36R; n=63 / −0.14R / −9R). The stub is orthogonalized
as of Phase 12 Part B; this baseline is superseded pending a re-run.

- **Survives** — score 6 is the only bucket positive in both splits
  (+0.15R n=299 / +0.03R n=105); nearly pure with-bias, so the engine's
  confluence measure is directionally informative.
- **Survives, and is the real signal** — 1–2-bar losses dominate (−0.34R n=316 /
  −0.23R n=188). The stub fires every 8 bars with no entry trigger and a fixed
  noise-width stop: it samples arbitrary moments, so −0.02R is a random sampler
  behaving exactly like one. Entry timing / stop placement is the weak joint.
- **Not attributable** — "counter-bias bleeds" and "the 3.5 stop bleeds" are one
  cohort; the cause could be side, stop width, docked score, or any mix.
- **Contaminated** — "low scores bleed": score 3 is largely probes docked from
  context score 6.
- **Train-only mirages** (killed by validation): side, structure kind, session,
  bias direction. **Not** stop distance — 3.5 was consistently worst in both
  splits because it was the probe cohort in disguise.
- Rejections are 100% session-filter, as configured.
