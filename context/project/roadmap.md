# Roadmap

Status legend: **Closed** · **Delivered (awaiting review)** · **Planned**.
As of 2026-07-07: Phase 00 Closed; Phases 01, 02, 03 Delivered (awaiting a single user review); Phase 04+ Planned.

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

## Phase 01 - Frontend Foundation — Delivered (2026-07-06, awaiting review)

Build the first dashboard shell in Next.js.

Deliverables:

- app shell
- navigation
- dashboard layout
- empty/loading/error states
- theme and UI conventions
- mock trading data contracts
- websocket client boundary and mock realtime event stream

## Phase 02 - Domain Model MVP — Delivered (2026-07-07, awaiting review)

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

## Phase 03 - MT5 Agent Specification — Delivered (2026-07-07, awaiting review)

Transform the existing EA into a future execution-agent specification.

Deliverables:

- EA capability map
- message contracts
- telemetry contracts
- execution command contracts
- websocket session lifecycle
- reconciliation workflow
- MQL5 refactor plan

## Phase 04 - ICT/SMC Engine MVP

Implement a first analysis engine outside MT5.

Deliverables:

- price engine
- swing engine
- liquidity engine
- FVG detector
- session engine
- market context output

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
