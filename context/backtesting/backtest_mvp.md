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
| `--every` | 8 | evaluate a signal every N bars (stub cadence) |
| `--max-bars` | 32 | outcome horizon before timeout (M15 → 8h) |
| `TRADINGOS_DB` | localhost:5433 | Postgres connection string |

## Honest limits (MVP)

No spread/slippage/commissions; binary exits; no account-level simulation
(daily lockouts, overlapping positions); historical spread gate reports "n/a".
Results grade the R distribution of signals, never account performance.
Deferred: cost modeling from stored ticks, equity-curve simulation, strategy
comparison, replay UI, charts.
