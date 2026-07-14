# Phase 12 - Backtest Diagnostics & Strategy Refinement

Status: Part A (diagnostics tooling) implemented 2026-07-14 per the user's spec (design validated in-session: 60/20/20 chronological splits; console+markdown report; OOS locked by tooling). Part B (data-driven refinement iterations) starts after joint review of the first report.

## Objective

Identify precisely the sources of losses BEFORE modifying any rule, under an anti-overfitting discipline; then iterate the strategy/engine with the backtester as the measured feedback loop. Costs and paper trading stay gated on an improved raw R distribution.

## Part A — delivered

- Schema: `backtest_trades` += `features jsonb` + `split`; new `backtest_rejections` (the "risk gates" dimension lives on refusals).
- Runner v2: frozen feature capture (ADR 0013 key set), time-based 60/20/20 split tagging, rejection recording, `--from/--to` filters.
- `lib/backtest/segments.ts` (pure, tested): per-bucket metrics, worst-first, `⚠ low n` flag (<30).
- `scripts/backtest-report.ts`: rejections + 15 dimension tables × split, console + `backtest-reports/<runId>.md`; **OOS hidden unless `--unlock-oos`**.
- Enriched baseline re-run `bt-mrkz8r44-d57578d8`: **bit-identical metrics to the Phase 11 baseline** (32.31% / −0.02R / −21.55R) — the pipeline is deterministic; 1,948 rejections captured (100% session filter).

## First findings (train + validation consistency required)

Robust (both splits, explainable):

1. **Counter-bias probes bleed**: train −0.19R (n=189), validation −0.14R (n=63). The stub injects them deliberately (1 in 4) — pure noise.
2. **Score works directionally**: score 3 bleeds in both (−0.23R/−0.49R); score 6 is the only bucket positive in both (+0.15R/+0.03R).
3. Structural insight (not a filter): **1–2-bar losses dominate** (−0.34R n=316 / −0.23R n=188) — entries die immediately; stop placement/entry timing is the weak joint.

Train-only mirages killed by validation: side, structure kind (BOS/CHOCH reversed), stop distance (6.5 best→worst), session edge, bias direction. Without the split these would have shipped as "improvements".

## Part B — refinement loop (pending joint review)

Candidate hypotheses for iteration 1 (to validate with the user): drop the counter-bias probe from the stub; add a minimum-score threshold to the strategy (risk engine stays a risk engine). One hypothesis per iteration, train-first, validation-confirmed, OOS once at the end.

## Gates

lint clean · source tsc exit 0 · 69 Vitest (13 backtest) · dotnet build 0/0 + 20/20 · schema applied idempotently to the live DB.
