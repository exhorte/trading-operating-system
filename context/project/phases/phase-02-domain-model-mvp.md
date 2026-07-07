# Phase 02 - Domain Model MVP

Status: implemented 2026-07-07 (see `phase-02-design.md`); awaiting user review before closure.

## Objective

Define the first platform contracts and domain types before connecting real execution.

## Candidate Models

- TradingAccount
- BrokerAccount
- Symbol
- Candle
- Tick
- Position
- Order
- Trade
- MarketContext
- LiquidityLevel
- FairValueGap
- OrderBlock
- SessionWindow
- RiskPolicy
- RiskState
- StrategySignal
- ExecutionCommand
- ExecutionReport
- RealtimeEnvelope
- RealtimeSubscription
- CommandAck

## Acceptance Criteria

- Types are explicit and documented.
- No UI component owns domain rules.
- Domain concepts can later map to .NET SignalR contracts and MQL5 WebSocket messages.

## Implementation Notes (2026-07-07)

- All candidate models exist: canonical schemas in `lib/domain/` (`primitives`, `market`, `account`, `analysis`, `risk`, `strategy`, `execution`); `RealtimeEnvelope` remains `lib/contracts/envelope.ts`; `RealtimeSubscription` and `CommandAck` payloads in `lib/contracts/commands.ts`.
- Symbol is modeled as `SymbolCode` (id) plus `SymbolMetadata` (broker attributes); MarketContext as `MarketContextState` with embedded ICT/SMC entities for replayability; RiskState as an aggregate, its old `"normal" | "warning" | "locked"` union renamed to `RiskMode` (legacy alias kept in `contracts/enums.ts`).
- `EventPayloadMap` in `lib/contracts/events.ts` now covers all 43 event types; `KnownEnvelope<T>` derives payload types from event names.
- No UI or runtime change: components still import only `lib/contracts` + `lib/realtime`; lint, typecheck, and build pass (11 routes).
- Mapping conventions to .NET/MQL5 documented in `context/domain/domain_model_mvp.md`; decision recorded in ADR 0004.
