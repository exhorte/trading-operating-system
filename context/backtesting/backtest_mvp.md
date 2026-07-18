# Backtesting MVP (Phase 11) — Runbook

Replays the live engines over stored history and grades signal quality.
Decision record: ADR 0012. **Hypothesis testing only** — engine v0.1, no
spread/slippage/costs, binary SL/TP exits (both-touch = conservative loss).

## Pipeline

```powershell
# 0 — database up (docker compose up -d) and backend built

# 1 — export ~1 year of M15 from the logged-in MT5 terminal (read-only)
cd tools/mt5-observer
python import_history.py --symbol XAUUSDm --bars 26000 --out candles.jsonl

# 2 — bulk-load into TimescaleDB (idempotent upsert)
cd ../..
npx tsx scripts/import-candles.ts tools/mt5-observer/candles.jsonl

# 3 — run the backtest (walk-forward, 300-bar window, signal every 8 bars,
#     32-bar outcome horizon by default)
npx tsx scripts/backtest.ts --symbol XAUUSDm --timeframe M15
```

The run prints its metrics and persists into `backtest_runs` / `backtest_trades`.

## View results

- Cockpit → **Backtests** page (list of runs, metrics, trades, hypothesis banner) —
  requires the backend host running (`GET /api/backtests`).
- SQL:

```sql
SELECT run_id, trade_count, win_rate, expectancy_r, cumulative_r, created_at
FROM backtest_runs ORDER BY created_at DESC;
SELECT outcome, count(*), round(avg(r_multiple)::numeric, 2) AS avg_r
FROM backtest_trades WHERE run_id = '<run>' GROUP BY outcome;
```

## Knobs

| Flag | Default | Meaning |
| --- | --- | --- |
| `--strategy` | sampler | `sampler` (periodic control) or `trigger` (iteration-1 FVG retest) |
| `--sessions` | all | strategy-layer session allowlist, CSV (iteration 2: `new_york_am`) |
| `--every` | 8 (sampler) / 1 (trigger) | evaluate every N bars — the trigger must see every bar, a retest can land on any of them |
| `--max-bars` | 32 | outcome horizon before timeout (M15 → 8h) |
| `--verdict-holdout` | — | Phase 13 single-read verdict: frozen candidate on the virgin holdout; rejects every other flag; requires a clean tree; refuses if a verdict exists or swap is needed but unmodeled |
| `TRADINGOS_DB` | localhost:5433 | Postgres connection string |

## Virgin holdout lock (Phase 13)

Ordinary runs **clip** every candle inside the virgin holdout
(2024-06-01T00:00Z → 2025-06-06T13:30Z exclusive, `lib/backtest/holdout.ts`)
and refuse ranges entirely inside it. The single `--verdict-holdout` read
computes gross + net (frozen cost profile `lib/backtest/costs.ts`) + an
informative stress scenario, classifies against the pre-registered bar
(`lib/backtest/verdict.ts`, seeded bootstrap → reproducible), and writes an
immutable row in `holdout_verdicts` (DB primary key = single read). Attempts,
including refusals, are audited in `holdout_attempts`. A technical failure
before the verdict row exists permits an audited retry; once the row exists
the holdout is consumed forever. The swap invariant refuses the verdict if any
trade crosses a 21:00/22:00 UTC rollover while the profile models no swap.

## Timeouts: role and exit rule

A trade that touches **neither** stop nor target within `--max-bars` future
bars exits as a `timeout` **at the close of the last horizon bar**
(`lib/backtest/outcome.ts`). Its R is the signed move from entry divided by
the initial risk — strictly between −1 and the reward multiple, since touching
either boundary would have decided the trade.

How the metrics treat them (`lib/backtest/metrics.ts`):

- **winRate and avgR exclude timeouts** — they are computed over *decided*
  trades only (win + loss);
- **expectancyR and cumulativeR include them** — expectancy is "the R of
  taking a signal", whatever the exit;
- a timeout with **negative** R counts toward loss streaks (`maxConsecLosses`).

Why this matters when reading trigger runs: with ATR-derived stops the horizon
truncates slow trades — the iteration-1 run has 17% timeouts (107/627) at
**positive** average R (+0.4R train / +0.35R validation), i.e. trades drifting
favourably that had not yet reached 2R. The win rate therefore *understates*
the arm's quality on its own; always read expectancyR (which includes the
timeout drift) alongside it. A timeout is an artifact of the measurement
horizon, not a strategy exit rule — the live platform has no equivalent
"close after 32 bars" behaviour. Widening `--max-bars` is a measurement
change, not a strategy change, but treat it like any knob: don't tune it
against results.

## Honest limits (MVP)

No spread/slippage/commissions; binary exits; no account-level simulation
(daily lockouts, overlapping positions); historical spread gate reports "n/a".
Results grade the R distribution of signals, never account performance.
Deferred: cost modeling from stored ticks, equity-curve simulation, strategy
comparison, replay UI, charts.
