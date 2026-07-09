# Roadmap

Status legend: **Closed** · **Delivered (awaiting review)** · **Planned**.
As of 2026-07-09: Phases 00–05 Closed; Phase 06 (Risk & Prop Firm Mode) and Phase 07 (Signal → Risk Review) Delivered (awaiting review); Phase 08+ Planned. Note: two phases were inserted ahead of the original plan (Live Observe Prototype as 05, Signal → Risk Review as 07), shifting Execution Bridge and Backtesting down.

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

## Phase 06 - Risk And Prop Firm Mode — Delivered (2026-07-08, awaiting review)

Build risk controls as independent services (pure TS, engine-first pattern; makes the observed account's risk panel real). Engine in `lib/risk/` (ADR 0008): gates + `evaluateRiskState` + `evaluateSignalRisk` (not wired). Deferred: news calendar, trailing drawdown, profit-target lockout, Friday/Sunday blocks, cooldown, ATR gate, multi-symbol sizing.

Deliverables:

- daily loss guard
- max drawdown guard
- risk per trade
- consecutive loss guard
- target reached lockout
- news/spread/volatility gates

## Phase 07 - Signal → Risk Review — Delivered (2026-07-09, awaiting review)

Wire the real risk engine into the signal pipeline: the mock emits domain signals from the computed market context, `evaluateSignalRisk` rules on each, and the audit-grade `risk.decision.made` contract carries the verdict. Live signals out of scope; execution loop deferred.

## Phase 08 - Execution Bridge

Connect server decisions to MT5 agent in a controlled environment.

Deliverables:

- command bus
- MT5 connector
- websocket gateway
- order lifecycle
- broker constraint handling
- idempotency
- audit logs

## Phase 09 - Backtesting And Analytics

Make decisions measurable and replayable.

Deliverables:

- historical data import
- scenario replay
- trade attribution
- metrics dashboard
- strategy comparison
