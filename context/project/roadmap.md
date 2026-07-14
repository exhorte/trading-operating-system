# Roadmap

Status legend: **Closed** · **Delivered (awaiting review)** · **Planned**.
As of 2026-07-14: Phases 00–11 Closed (Phase 11 baseline: engine v0.1 has NO edge — 32.31% win rate, −0.02R expectancy over 1,261 trades); Phase 12 (Backtest Diagnostics & Strategy Refinement) is the active next phase. Cost modeling and paper trading stay explicitly gated on an improved raw R distribution. Note: phases were inserted ahead of the original plan (Live Observe Prototype as 05, Signal → Risk Review as 07, Backend Bootstrap as 08), shifting Execution Bridge and Backtesting down.

## Phase 00 - AI Project Brain Bootstrap — Closed (2026-07-06)

Create `.claude/` and `context/` so Claude Code can work with durable project memory.

Deliverables:

- Claude operating instructions
- project manifesto
- system overview
- domain summaries
- EA analysis
- roadmap and phase system
- governance and quality gates

## Phase 01 - Frontend Foundation — Closed (2026-07-08)

Build the first dashboard shell in Next.js.

Deliverables:

- app shell
- navigation
- dashboard layout
- empty/loading/error states
- theme and UI conventions
- mock trading data contracts
- websocket client boundary and mock realtime event stream

## Phase 02 - Domain Model MVP — Closed (2026-07-08)

Define platform contracts before real trading.

Deliverables:

- account model
- symbol model
- candle/tick model
- trade/order/position model
- market context model
- risk policy model
- strategy signal model
- realtime event envelope
- command/ack/report contracts

## Phase 03 - MT5 Agent Specification — Closed (2026-07-08)

Transform the existing EA into a future execution-agent specification.

Deliverables:

- EA capability map
- message contracts
- telemetry contracts
- execution command contracts
- websocket session lifecycle
- reconciliation workflow
- MQL5 refactor plan

## Phase 04 - ICT/SMC Engine MVP — Closed (2026-07-08)

Implement a first analysis engine outside MT5, in pure TypeScript (`lib/analysis/`, ADR 0006).

Deliverables:

- price/candle intake
- swing engine
- market structure (BOS/CHOCH)
- liquidity engine (equal highs/lows, PDH/PDL, swept)
- FVG + order-block detector
- session engine
- bias + weighted scoring
- market context output (`MarketContextState`) + read-model projection

Deferred to later phases: SMT/divergence, news/macro, premium-discount OTE, breaker/mitigation blocks, entry-sequence and trade-management engines (see `engineering/analysis_engine_mvp.md`).

## Phase 05 - Live Observe Prototype — Closed (2026-07-08, validated live)

Stream real MT5 demo data into the cockpit in read-only `observe` mode to validate the connection chain (ADR 0007).

Deliverables:

- Python `MetaTrader5` read-only producer (`tools/mt5-observer/`)
- lean-wire WebSocket + browser `LiveRealtimeClient` + pure translation mappers
- real M15 candles → Phase 04 ICT/SMC engine → Market Context
- DEMO badge, opt-in via env (mock stays default)

Prototype only: browser-side translation is a shortcut; the production path keeps the .NET gateway (ADR 0005) + MQL5 EA/sidecar (Phase 03).

## Phase 06 - Risk And Prop Firm Mode — Closed (2026-07-10)

Build risk controls as independent services (pure TS, engine-first pattern; makes the observed account's risk panel real). Engine in `lib/risk/` (ADR 0008): gates + `evaluateRiskState` + `evaluateSignalRisk` (not wired). Deferred: news calendar, trailing drawdown, profit-target lockout, Friday/Sunday blocks, cooldown, ATR gate, multi-symbol sizing.

Deliverables:

- daily loss guard
- max drawdown guard
- risk per trade
- consecutive loss guard
- target reached lockout
- news/spread/volatility gates

## Phase 07 - Signal → Risk Review — Closed (2026-07-10)

Wire the real risk engine into the signal pipeline: the mock emits domain signals from the computed market context, `evaluateSignalRisk` rules on each, and the audit-grade `risk.decision.made` contract carries the verdict. Includes the `/signals` audit workspace and rotating mock scenarios (real rejections). Live signals out of scope; execution loop deferred.

## Phase 08 - ASP.NET Core Backend Bootstrap — Closed (2026-07-11, validated live)

Stand up the real backend: host, SignalR hub for the dashboard, WebSocket Gateway ingesting the lean MT5 wire (replaces the Phase 05 browser-side translation, ADR 0007), C# mirrors of domain/contract schemas (ADR 0004).

Deliverables:

- ASP.NET Core solution (modular monolith)
- SignalR hub broadcasting `Envelope<T>` to the dashboard
- WebSocket Gateway for the lean MT5 wire (mt5-wire)
- C# domain/contract mirrors
- dashboard SignalR client behind the RealtimeClient seam

## Phase 09 - Execution Bridge — Closed (2026-07-11, observe/SIMULATED slice, validated live)

Connect decisions to the MT5 agent in a controlled environment. This slice (ADR 0010): full command loop in observe mode — risk-gated command builder, hub mode guard, lean flatten, agent validation/dedup/ack, SIMULATED reports, store lifecycle, timeout + single idempotent retry. Deferred: modify/close/cancel, paper/live terminal actions (gated on persistence).

## Phase 10 - Persistence — Closed (2026-07-12, validated live)

PostgreSQL/TimescaleDB before any paper trading (user decision): commands, risk decisions, acks, reports, candles, ticks and the full JSONB envelope audit are written server-side (ADR 0011). Docker compose (port 5433), Dapper + idempotent schema.sql, never-blocking bounded-channel writer, hub-published signals (multi-tab consistent), `/api/audit/recent` read proof. Deferred: replay UI, DB-backed P&L, retention/compression, backups.

## Phase 11 - Backtesting MVP — Closed (2026-07-14, baseline: no edge)

The manifesto's "backtest before confidence" step (ADR 0012). A Node runner replays the SAME pure TS engines (ICT/SMC + risk + strategy stub) walk-forward over stored candles and grades signal quality.

Deliverables:

- historical M15 import (read-only Python export → JSONL → idempotent bulk upsert)
- `lib/backtest` pure outcome + metrics (conservative both-touch, timeouts)
- `scripts/backtest.ts` runner (300-bar window like live, engine version tagged)
- `backtest_runs`/`backtest_trades` tables + `GET /api/backtests(/{id})`
- Backtests page (runs, metrics, trades) under a permanent hypothesis banner

Deferred to a later phase: cost modeling (spread/slippage/commissions from stored ticks), account-level simulation (daily lockouts, overlapping positions, equity curve), strategy comparison, replay UI, charts.

## Phase 12 - Backtest Diagnostics & Strategy Refinement

Identify precisely where the losses come from before modifying any rule: segmented analyses (side, session, day/month, bias, BOS/CHOCH, FVG/OB, score, liquidity type, planned RR, duration, timeout, both-touch, risk gates) with a train/validation/out-of-sample discipline against overfitting. Then data-driven refinement iterations measured by the backtester.

## Phase 13+ - Costs, Simulation & Paper Trading (Planned, gated)

Cost modeling (spread/slippage/commissions), account-level simulation (equity curve, lockouts, overlapping positions), replay UI, DB-backed P&L calendar, then the paper-trading track — all gated on an improved raw R distribution from Phase 12.
