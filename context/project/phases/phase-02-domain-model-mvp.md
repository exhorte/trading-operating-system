# Phase 02 - Domain Model MVP

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
