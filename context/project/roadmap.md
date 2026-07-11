# Roadmap

Status legend: **Closed** · **Delivered (awaiting review)** · **Planned**.
As of 2026-07-11: Phases 00–09 Closed (Phase 09 validated live, real DUPLICATE-dedup exercised); Phase 10 = Persistence (PostgreSQL/Timescale, before any paper trading) is the active next phase; Backtesting shifts to 11. Note: phases were inserted ahead of the original plan (Live Observe Prototype as 05, Signal → Risk Review as 07, Backend Bootstrap as 08), shifting Execution Bridge and Backtesting down.

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

## Phase 10 - Persistence

PostgreSQL/TimescaleDB before any paper trading (user decision): store commands, risk decisions, acks, reports, candles, and audit traces; enable replay and the P&L calendar on real data.

## Phase 11 - Backtesting And Analytics

Make decisions measurable and replayable.

Deliverables:

- historical data import
- scenario replay
- trade attribution
- metrics dashboard
- strategy comparison
