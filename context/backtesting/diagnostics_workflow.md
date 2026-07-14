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
3. **Multi-comparison guard.** 13+ dimensions × buckets will produce flukes.
   Act only on effects that are (a) strong, (b) mechanically explainable,
   (c) consistent across train AND validation, (d) not `⚠ low n` (<30 trades).
4. **One hypothesis per iteration**, recorded in the brain (what/why/expected
   effect), then measured. Keep the run ids; runs are cheap, amnesia is not.
5. Costs and paper trading stay out until the RAW R distribution improves.

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

Consistent train+validation: counter-bias probes bleed (−0.19R/−0.14R); low
scores bleed (score 3: −0.23R/−0.49R) while score 6 is positive in both; 1–2-bar
losses dominate (entry timing / stop placement is the structural weakness).
Train-only mirages (killed by validation): side, structure kind, stop distance,
session, bias direction. Rejections are 100% session-filter, as configured.
