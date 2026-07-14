# Phase 11 - Backtesting MVP

Status: implemented 2026-07-12 (design validated first: Backtesting MVP scope; ~1 year of M15 history). Awaiting the user's first import + run + review of results before closure.

## Objective

Make the manifesto's "backtest before confidence" step real: import broker history into TimescaleDB, replay the SAME pure TS engines (ICT/SMC + risk + strategy stub) walk-forward over stored candles, simulate each approved signal's outcome, persist runs, and render them in the Backtests page under a permanent hypothesis banner.

## Scope

In scope: `import_history.py` (read-only JSONL export) + `scripts/import-candles.ts` (idempotent bulk upsert), `lib/backtest/{outcome,metrics}.ts` (pure, tested — conservative both-touch rule, timeout exits), `scripts/backtest.ts` runner (tsx; 300-bar rolling window like live; run + trades persisted with engine version), `backtest_runs`/`backtest_trades` tables, `GET /api/backtests(/{id})`, real Backtests page.

Deferred (ADR 0012): cost modeling (spread/slippage/commissions), account-level simulation (daily lockouts, overlapping positions), strategy comparison, replay UI, charts.

## Acceptance Criteria

- ≥ ~1 year of M15 XAUUSDm in `candles`; re-import idempotent.
- `npx tsx scripts/backtest.ts` persists a run with trades and metrics (win rate, avg R decided, expectancy R, max consecutive losses, cumulative R, both-touch count); `lib/backtest` unit-tested (9 tests: SL/TP/both-touch/timeout/sell/degenerate + metrics).
- Backtests page lists runs and details trades under the hypothesis banner; honest empty/unreachable states.
- Gates: lint/tsc/Vitest, dotnet build+test, py_compile.

## Implementation Notes (2026-07-12)

Built as designed. Dev-only deps added: `tsx`, `pg`, `@types/pg`. The runner reuses the engines unmodified — the payoff of the pure-engine/no-look-ahead discipline held since Phase 04. Backend read endpoints follow the audit-endpoint error discipline (log + surface the real exception; timestamptz→DateTime mapping lesson applied to `BacktestRepository`).
