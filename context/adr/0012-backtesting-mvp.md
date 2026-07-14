# ADR 0012 - Backtesting MVP: Node Runner Reusing The Pure TS Engines

## Status

Accepted

## Context

The manifesto demands "backtest and forward-test before confidence", and every engine since Phase 04 is tagged `v0.1 — hypothesis, not a validated edge`. With persistence in place (Phase 10), the platform can finally measure the hypothesis. Decisions validated by the user (2026-07-12): Backtesting MVP as Phase 11, ~1 year of M15 history.

## Decision

1. **The backtest runner is a Node CLI (`scripts/backtest.ts`, run via `tsx`) that imports the SAME pure TS engines the platform runs live** — `lib/analysis` (ICT/SMC), `lib/risk` (FTMO gates + sizing), the strategy stub, and the new `lib/backtest` modules. No engine port, no reimplementation: the no-look-ahead invariant (tested since Phase 04) is what makes historical replay legitimate. Walk-forward with the same 300-bar rolling window as the live clients.
2. **History import**: `tools/mt5-observer/import_history.py` (read-only, no credentials, zero trade imports) dumps closed M15 bars as JSONL; `scripts/import-candles.ts` bulk-upserts into the `candles` hypertable (idempotent). Dev-only deps added: `tsx`, `pg`, `@types/pg`.
3. **Outcome model (`lib/backtest/outcome.ts`, pure + tested)**: binary exits — first bar touching SL or TP decides; a bar touching BOTH applies the conservative rule (stop first = loss) and is flagged `bothTouch` (rate surfaced in results); no exit within `maxBars` → timeout at that bar's close. **No spread, slippage or commissions in the MVP** — stated everywhere.
4. **Metrics (`lib/backtest/metrics.ts`, pure + tested)**: win rate over decided trades, avg R (decided), expectancy R (all trades incl. timeouts), max consecutive losses (negative timeouts count), cumulative R, both-touch count.
5. **Persistence**: `backtest_runs` + `backtest_trades` tables (idempotent additions to `schema.sql`), every run tagged with the engine version and its config JSON.
6. **Read surface**: `GET /api/backtests` and `GET /api/backtests/{runId}` on the host (HTTP export surface, same error-logging discipline as the audit endpoint); the Backtests page renders runs, metrics and trades under a permanent **hypothesis banner**.

## Consequences

- The engine v0.1 hypothesis is finally measurable on real broker history — the gate that must be passed before paper trading means anything.
- Results grade **signal quality (R distribution)**, not account performance: no costs, no daily-loss lockouts over an equity curve, no position overlap constraints. These belong to a later, fuller simulation.
- The pure-engine pattern pays off exactly as intended: live and backtest share one code path, so a backtest improvement is a live improvement.
- Deferred: cost modeling (spread from stored ticks), account-level simulation (daily lockouts, concurrent positions), strategy comparison across configs, replay UI, charts on the Backtests page.
