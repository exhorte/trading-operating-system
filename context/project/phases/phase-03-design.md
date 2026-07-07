# Phase 03 Design - MT5 Agent Specification

Status: specification written 2026-07-07 after the user fixed the three load-bearing decisions below. This phase produces documentation and wire contracts, not executable trading code.

## Objective

Turn the EA knowledge (`context/domain/ea_analysis.md`) and the Phase 02 domain schemas into a complete specification for an MT5 execution-and-telemetry agent: its wire protocol, session lifecycle, execution lifecycle, safety guards, and how it reconciles with the platform.

## Decisions Fixed By The User (2026-07-07)

1. **Two separate transport worlds.** At the MT5 edge the agent speaks **secure WebSocket (WSS) + versioned lean JSON**, not SignalR. A **WebSocket Gateway** (.NET) translates that lean JSON into the internal `Envelope<T>` and Phase 02 domain models. SignalR is used only between the backend and the Next.js dashboard. Rationale: MQL5 has no maintained SignalR client; `Connect → Send → Receive → Reconnect` over raw WSS is simple and reliable, and the gateway isolates the two protocol worlds.

   ```text
   Next.js Dashboard
        │  SignalR
   Trading API
   Trading Engine
        │  WebSocket Gateway   (translates MT5 lean JSON ↔ internal events)
        │  WSS + versioned JSON
   MT5 Agent
   ```

2. **Full command loop from sprint 1, gated by execution modes.** The agent receives the exact same command in every mode; only the terminal action differs.
   - `observe` — never sends to broker; replies `{ "status": "SIMULATED", "commandId": ... }`. Validates protocol, serialization, ACKs, errors, timeouts, reconnects at zero risk.
   - `paper` — routes to a demo account.
   - `live` — routes to the FTMO broker.

   Same agent code; only configuration changes (`execution.enabled`, `execution.mode`). On the backend the Trading Engine talks to an `ExecutionAdapter` abstraction with `NullExecution` / `PaperExecution` / `MT5Execution` / future `FIXExecution`; the engine never knows which is active.

3. **External sidecar bridge for MQL5 networking.** The EA exchanges lean JSON with a small local sidecar process (named pipe / localhost socket); the sidecar holds the WSS connection to the gateway and owns reconnect/framing. The sidecar is a dumb transport relay — no business logic — so MQL5 trading callbacks are never blocked.

## Existing Context

- `context/realtime/mt5_agent_realtime_lifecycle.md` — lifecycle, connection states, local guards, reconnect flow (kept; extended in this phase with the sidecar and execution modes).
- `context/domain/ea_analysis.md` — the 7-component refactor target (`MarketDataPublisher`, `AccountStatePublisher`, `ExecutionCommandReceiver`, `OrderExecutor`, `ExecutionReporter`, `LocalRiskGuard`, `ConnectionSupervisor`).
- `context/domain/risk_ftmo.md` — risk approval precedes execution; the agent only holds emergency local guards.
- `lib/contracts/` + `lib/domain/` (Phase 02) — the internal envelope and domain models the gateway maps to.
- ADR 0003 (WebSocket-first), ADR 0004 (TypeScript as canonical schema source).

## Impact Analysis

- The MT5 edge protocol is **deliberately leaner** than the internal `Envelope<T>`: flat fields, `version` not `schemaVersion`, epoch `time`, uppercase `side`, `id` not `commandId`, no `messageId`/`correlationId`/`causationId`. The gateway is exactly the adapter that enriches inbound and flattens outbound. This must be documented as a two-layer wire design, not treated as drift from Phase 02.
- New canonical artifact: the lean edge protocol as TypeScript (`lib/contracts/mt5-wire.ts`), consistent with ADR 0004. The EA (MQL5) and the gateway (.NET) mirror it.
- No product/runtime code changes in this Next.js repo; the EA, sidecar, and gateway do not live here yet.

## Proposed Architecture

Component responsibilities inside the agent (from `ea_analysis.md`, now bound to modes and the sidecar):

| Component | Responsibility |
| --- | --- |
| `ConnectionSupervisor` | talk to the sidecar; drive the connection state machine; trigger resync on reconnect |
| `MarketDataPublisher` | emit `market.tick`, `market.candle` |
| `AccountStatePublisher` | emit `account.snapshot`, `positions.snapshot`, `agent.heartbeat` |
| `ExecutionCommandReceiver` | receive `execution.*` commands; dedupe by `id`; check `expiresAt` |
| `LocalRiskGuard` | final emergency guards (trading disabled, unsupported symbol, volume/stops out of bounds, market closed, account mismatch, stale connection) — never replaces server risk |
| `OrderExecutor` | apply the execution mode: `observe` → SIMULATED, `paper`/`live` → broker order |
| `ExecutionReporter` | emit `execution.ack` then `execution.report` echoing the command `id` |

## Data Flow

```text
tick/candle/account → MarketData/AccountState Publisher → sidecar → WSS → Gateway
   → enrich to Envelope<T> + domain model → Trading Engine

Trading Engine → ExecutionCommand → Gateway flatten to lean execution.order
   → WSS → sidecar → EA → ExecutionCommandReceiver → LocalRiskGuard → OrderExecutor
   → ExecutionReporter (ack, then report with command id) → back up the same path
```

Reconnect: sidecar re-establishes WSS → agent re-registers (`agent.hello`) → sends account + positions snapshots → gateway/engine reconcile open positions and pending commands → execution re-enabled only after reconciliation.

## Files To Create Or Modify

Create: `context/realtime/mt5_wire_protocol.md` (lean protocol reference + gateway translation tables + execution modes), `lib/contracts/mt5-wire.ts` (canonical lean-edge TS types), `context/adr/0005-mt5-lean-wire-and-gateway.md`, this design doc.

Modify: `context/realtime/mt5_agent_realtime_lifecycle.md` (add sidecar + execution-mode sections), `context/project/phases/phase-03-mt5-agent-spec.md` (implementation notes), `context/project/{project_state,handoff,changelog}.md`.

## Risks

- Scope creep into building the EA/sidecar/gateway: Phase 03 is specification only. No MQL5, no .NET here yet.
- Silent divergence between the lean edge protocol and the internal envelope: mitigated by the gateway translation tables and by `mt5-wire.ts` referencing the same domain vocabulary.
- Mode confusion causing a real order in `observe`: mitigated by making `observe` the default (`execution.enabled: false`) and by the `LocalRiskGuard` treating unknown/absent mode as `observe`.

## Acceptance Criteria (from phase-03-mt5-agent-spec.md)

- Message contracts documented — `mt5_wire_protocol.md` + `mt5-wire.ts`.
- WebSocket session lifecycle documented — lifecycle doc extended (sidecar, states, reconnect).
- Execution lifecycle documented — command → ack → report, per mode.
- Retry, idempotency, reconciliation specified — dedupe by `id`, `expiresAt`, snapshot-before-trust on reconnect.
- EA strategy logic mapped into reusable concepts — component table + `ea_analysis.md` link.

## Implementation Checklist

1. [x] Write this design document.
2. [x] Write `context/realtime/mt5_wire_protocol.md` (messages, envelope, examples, mode behavior, gateway mapping).
3. [x] Write `lib/contracts/mt5-wire.ts` canonical lean-edge types.
4. [x] Extend `mt5_agent_realtime_lifecycle.md` with sidecar + execution modes + reconciliation.
5. [x] Write ADR 0005.
6. [x] Verify lint + typecheck (mt5-wire.ts).
7. [x] Update phase file, project state, handoff, changelog.
