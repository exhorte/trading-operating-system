# Roadmap

Status legend: **Closed** · **Delivered (awaiting review)** · **Planned**.
As of 2026-07-08: Phases 00, 01, 02, 03 Closed; Phase 04 (ICT/SMC Engine MVP) Delivered (awaiting review); Phase 05+ Planned.

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

## Phase 04 - ICT/SMC Engine MVP — Delivered (2026-07-08, awaiting review)

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

## Phase 05 - Risk And Prop Firm Mode

Build risk controls as independent services.

Deliverables:

- daily loss guard
- max drawdown guard
- risk per trade
- consecutive loss guard
- target reached lockout
- news/spread/volatility gates

## Phase 06 - Execution Bridge

Connect server decisions to MT5 agent in a controlled environment.

Deliverables:

- command bus
- MT5 connector
- websocket gateway
- order lifecycle
- broker constraint handling
- idempotency
- audit logs

## Phase 07 - Backtesting And Analytics

Make decisions measurable and replayable.

Deliverables:

- historical data import
- scenario replay
- trade attribution
- metrics dashboard
- strategy comparison
