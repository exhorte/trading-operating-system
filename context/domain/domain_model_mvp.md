# Domain Model MVP (Phase 02)

The canonical domain schemas live in `lib/domain/` as portable TypeScript. This document explains the layering, the portability rules, and the mapping conventions toward .NET SignalR contracts and MQL5 WebSocket messages.

## Layering

```
lib/domain/      canonical domain schemas (accounts, market, analysis, risk, strategy, execution)
   ▲
lib/contracts/   wire layer: Envelope, EventType registry, event/command payloads, dashboard read models
   ▲
lib/realtime/    client seam: RealtimeClient, CockpitStore, MockRealtimeClient, React provider
   ▲
components/      UI — never owns domain rules, never imports the mock client
```

Dependency direction is strictly downward-to-upward as drawn: `contracts` may import `domain`; `domain` imports nothing outside itself.

## Module Map

| Module | Models |
| --- | --- |
| `domain/primitives.ts` | id aliases, `UtcTimestamp`, `Timeframe`, `Side`, `Bias`, `TradingSession` |
| `domain/market.ts` | `SymbolMetadata`, `Tick`, `Candle`, `SpreadSample`, `SessionWindow` |
| `domain/account.ts` | `BrokerAccount`, `TradingAccount`, `AccountKind` |
| `domain/analysis.ts` | `LiquidityLevel`, `FairValueGap`, `OrderBlock`, `StructureShift`, `ScoreComponent`, `MarketContextState` |
| `domain/risk.ts` | `RiskPolicy`, `RiskMode`, `RiskGateResult`, `RiskState`, `RiskDecision` |
| `domain/strategy.ts` | `SignalStatus`, `StrategySignal` |
| `domain/execution.ts` | `Order`, `Position`, `Trade`, `ExecutionCommand` (union of `PlaceOrderCommand`, `ModifyPositionCommand`, `ClosePositionCommand`, `CloseAllCommand`, `CancelOrderCommand`), `CommandAck`, `ExecutionReport`, `ExecutionAgent` |
| `contracts/envelope.ts` | `Envelope`, `EventType` registry |
| `contracts/commands.ts` | command payloads, `CommandAckPayload`, `RealtimeSubscription`, `SubscriptionTopic` |
| `contracts/events.ts` | event payloads, `EventPayloadMap` (exhaustive `EventType` → payload), `KnownEnvelope<T>` |
| `contracts/snapshots.ts` | dashboard read models (view layer, not domain) |

## Portability Rules

These rules make the TypeScript schemas mechanically translatable to C# records and MQL5 structs:

1. Plain `interface` and string-literal unions only — no classes, methods, generics in data shapes, or `Date` objects.
2. Absent values are explicit `null`, never omitted properties or `undefined`.
3. Timestamps are ISO 8601 UTC strings (`UtcTimestamp`). .NET: `DateTimeOffset`. MQL5: parse/format explicitly at the agent boundary.
4. Numbers are IEEE doubles. Volumes are lots. Percentages use the 0-100 scale. Money is in account currency.
5. JSON on the wire is camelCase. .NET uses PascalCase properties with a camelCase serializer policy. MQL5 field names map manually in the agent's serializer.
6. Discriminated unions use a string discriminator (`kind` on `ExecutionCommand`); .NET maps to polymorphic serialization or a switch on `kind`.
7. Schema evolution rides `Envelope.schemaVersion`; breaking payload changes bump it.

## Traceability Chain

The audit requirement "every trade decision traceable to market, risk, strategy, and execution context" is encoded in the ids:

`MarketContextState` (embedded) → `StrategySignal.signalId` → `RiskDecision.approvalId` → `ExecutionCommand.commandId` (carries `riskApprovalId`, mandatory) → `CommandAck.commandId` → `ExecutionReport.commandId` → `Position.signalId` → `Trade.positionId`.

## Dashboard Read Models vs Domain Models

`contracts/snapshots.ts` (e.g. `AccountSummary`, `RiskStatus`, `MarketContext`) are flattened projections the server pushes to the cockpit; they are optimized for rendering, not for decisions. The domain models are the decision-grade shapes. Both are legitimate wire payloads on different channels (dashboard vs agent/backend), per `context/realtime/dashboard_realtime_model.md`.

## Known Phase 01 Shortcuts (to reconcile when the store adopts EventPayloadMap)

- The mock feed publishes `execution.command.acknowledged` with an `ExecutionReportPayload`; the canonical agent-channel payload is `CommandAckPayload`.
- `risk.command.approved`/`rejected` reach the dashboard as `SignalUpdatedPayload`; the decision-grade record is `RiskDecision` and will need its own audit channel event.
- `contracts/enums.ts` re-exports domain `RiskMode` under the legacy name `RiskState` for Phase 01 compatibility.
