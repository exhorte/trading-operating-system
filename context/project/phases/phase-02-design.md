# Phase 02 Design - Domain Model MVP

Status: implemented 2026-07-07 (direct continuation requested by user).

## Objective

Formalize the platform's domain vocabulary into explicit, documented, portable TypeScript schemas before any real backend or execution work. After this phase, every concept the platform manipulates (account, symbol, candle, trade, market context, risk, signal, execution, realtime envelope) has one canonical definition that can later be mirrored to .NET SignalR contracts and MQL5 WebSocket messages.

## Existing Context

- Phase 01 shipped `lib/contracts/` (envelope, enums, event payloads, dashboard read models) as UI-facing types. `project_state.md` designates it as the seed of Phase 02.
- `context/realtime/event_contracts.md` is the conceptual source of truth for the envelope and event families.
- `context/domain/trading_ontology.md`, `risk_ftmo.md`, `ict_smc_framework.md` define the domain vocabulary.
- The UI depends only on `CockpitStore`, `RealtimeClient`, and the types in `lib/contracts/` — never on the mock client. This seam must survive intact.

## Impact Analysis

- `lib/contracts/snapshots.ts` types are **dashboard read models**, not domain models. They stay where they are; Phase 02 must not force a UI rewrite.
- `lib/contracts/enums.ts` mixes two kinds of vocabulary: client/UI state (`ConnectionState`, `Environment`) and domain vocabulary (`Side`, `Bias`, `TradingSession`, `SignalStatus`, `AgentState`, `ExecutionReportStatus`, `RiskState`). The domain vocabulary moves to `lib/domain/` and is re-exported from `enums.ts` so every existing import keeps compiling.
- `CockpitStore`, `MockRealtimeClient`, and all components are untouched.
- Naming collision: Phase 01 used `RiskState` for the `"normal" | "warning" | "locked"` union, while the domain needs a `RiskState` aggregate. Resolution: the union becomes `RiskMode` in the domain; `contracts/enums.ts` re-exports it under the old `RiskState` alias for backward compatibility.

## Proposed Architecture

Two layers with a strict dependency direction: `lib/contracts` (wire) → `lib/domain` (canonical). UI keeps importing from `lib/contracts` and `lib/realtime`.

### `lib/domain/` — canonical portable schemas

| File | Models |
| --- | --- |
| `primitives.ts` | id aliases (`AccountId`, `SymbolCode`, …), `UtcTimestamp`, `Timeframe`, `Side`, `Bias`, `TradingSession` |
| `market.ts` | `SymbolMetadata`, `Tick`, `Candle`, `SpreadSample`, `SessionWindow` |
| `account.ts` | `BrokerAccount`, `TradingAccount` |
| `analysis.ts` | `LiquidityLevel`, `FairValueGap`, `OrderBlock`, `StructureShift`, `MarketContextState` |
| `risk.ts` | `RiskPolicy`, `RiskMode`, `RiskGateResult`, `RiskState`, `RiskDecision` |
| `strategy.ts` | `SignalStatus`, `StrategySignal` |
| `execution.ts` | `OrderType`, `OrderStatus`, `Order`, `Position`, `Trade`, `ExecutionCommand` (discriminated union), `CommandAck`, `ExecutionReportStatus`, `ExecutionReport`, `AgentState`, `ExecutionAgent` |
| `index.ts` | barrel |

Portability rules (documented in `context/domain/domain_model_mvp.md`):

- Plain `interface`/string-literal unions only. No classes, no `Date`, no functions, no optional-`undefined` fields — absent values are explicit `null`.
- Timestamps are ISO 8601 UTC strings (`UtcTimestamp`); .NET maps to `DateTimeOffset`, MQL5 converts explicitly.
- All numbers are IEEE doubles; volumes are lots; percentages are 0-100 scale.
- JSON is camelCase on the wire; .NET uses PascalCase properties with camelCase serialization; discriminated unions use a string discriminator field (`kind` for commands).

### `lib/contracts/` — wire layer

- `envelope.ts` — unchanged shape; `EventType` stays the event-name registry.
- `commands.ts` (new) — payloads for `execution.command.*`, `CommandAckPayload`, `RealtimeSubscription` + `dashboard.subscribe`/`unsubscribe`/`snapshot.requested` payloads.
- `events.ts` — existing Phase 01 payloads untouched; adds payloads for the remaining event families (candles, spread, symbol metadata, liquidity/FVG/structure/bias, lockout, agent lifecycle/error) and an `EventPayloadMap` + `KnownEnvelope<T>` so producers/consumers can be exhaustively typed.
- `enums.ts` — becomes re-exports of domain vocabulary plus the client-only `ConnectionState`/`Environment`.
- `snapshots.ts` — unchanged (dashboard read models), now importing its enums transitively from the domain.

## Data Flow

Unchanged at runtime: mock generators → `Envelope<T>` → `RealtimeClient` → `CockpitStore` → UI. What changes is where the types come from: payloads reference domain models, so a future ASP.NET Core hub and MT5 agent implement the same schema set.

## Files To Create Or Modify

Create: `lib/domain/{primitives,market,account,analysis,risk,strategy,execution,index}.ts`, `lib/contracts/commands.ts`, `context/domain/domain_model_mvp.md`, `context/adr/0004-typescript-domain-schema-source.md`, this design doc.

Modify: `lib/contracts/enums.ts` (re-export from domain), `lib/contracts/events.ts` (extend), `context/project/{project_state,handoff,changelog}.md`, `context/project/phases/phase-02-domain-model-mvp.md`.

## Risks

- Scope creep into behavior: Phase 02 defines **data shapes only**; no engines, no validation logic, no persistence.
- Silent divergence between `context/realtime/event_contracts.md` and `lib/contracts/`: mitigated by `EventPayloadMap` covering every `EventType`.
- Renaming `RiskState` → `RiskMode` could break the UI: mitigated by the compatibility re-export and verified by lint + build.

## Acceptance Criteria

- Every candidate model from `phase-02-domain-model-mvp.md` exists, documented, in `lib/domain/` or `lib/contracts/`.
- Every `EventType` has a typed payload in `EventPayloadMap`.
- No UI component owns domain rules; no component import changes.
- `npm run lint` and `npm run build` pass.
- Project brain updated (state, handoff, changelog, ADR 0004).

## Implementation Checklist

1. [x] Write this design document.
2. [x] Create `lib/domain/` modules and barrel.
3. [x] Rewire `lib/contracts/enums.ts` as re-exports; keep `ConnectionState`/`Environment` local.
4. [x] Add `lib/contracts/commands.ts`; extend `lib/contracts/events.ts` with full payload coverage and `EventPayloadMap`.
5. [x] Write `context/domain/domain_model_mvp.md` and ADR 0004.
6. [x] Verify lint + typecheck + build (11 routes, no UI change).
7. [x] Update project state, handoff, changelog, phase file.
