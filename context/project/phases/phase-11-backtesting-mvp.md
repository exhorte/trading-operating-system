# Phase 11 - Backtesting MVP

Status: closed 2026-07-14 (implemented 2026-07-12, committed `d7d9106`; design validated first). **First real run completed and reviewed by the user** — the pipeline is validated as a technical and statistical baseline, and the result is honestly negative:

- Run `bt-mrkx74n5-500ff1f8`, XAUUSDm M15, 2025-06-06 → 2026-07-14, 25,999 candles.
- 3,209 signals → 1,261 approved (≈39%) → 1,261 trades.
- **Win rate 32.31%** (2R targets → theoretical break-even ≈33.3%), **avg R −0.03**, **expectancy −0.02R**, **cumulative −21.55R**, max 21 consecutive losses, 54 both-touch bars.
- Conclusion (user): **engine v0.1 has no positive edge on this period, even before spread/commissions/slippage** — statistically near-random for a stub strategy, as expected. **No paper trading in this state.**

The negative result is the deliverable: the manifesto's "backtest before confidence" gate now produces numbers instead of hopes. Next: Phase 12 — Backtest Diagnostics & Strategy Refinement (segmented loss analysis + train/validation/out-of-sample discipline) before touching any rule.

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
