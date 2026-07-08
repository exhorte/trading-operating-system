# Phase 03 - MT5 Agent Specification

## Objective

Convert the existing EA knowledge into a specification for an MT5 execution and telemetry agent.

## Source

`../NOTES/Ultimate_ICT_Gold_Scalper_v4.0.mq5`

## Target Role

The MT5 agent must:

- stream ticks/candles/account state to the server
- receive execution commands through a persistent WebSocket/SignalR-compatible channel
- execute broker orders
- report confirmations, rejections, fills, and position updates
- enforce emergency local safety gates
- survive reconnects and terminal restarts

## Non-Goals

- It must not own final strategy decisions.
- It must not run hidden grid or martingale logic.
- It must not silently change risk policy.

## Acceptance Criteria

- Message contracts are documented.
- WebSocket session lifecycle is documented.
- Execution lifecycle is documented.
- Retry, idempotency, and reconciliation are specified.
- Existing EA strategy logic is mapped into reusable concepts.

## Specification Notes (2026-07-07)

Design and decisions in `phase-03-design.md` (three user decisions: lean WSS+JSON edge with a translating gateway, full command loop gated by execution modes, external sidecar bridge). Deliverables:

- Message contracts — `context/realtime/mt5_wire_protocol.md` (lean edge protocol, examples, gateway translation tables) + `lib/contracts/mt5-wire.ts` (canonical lean-edge TS types, mirrors the internal envelope via the gateway).
- Session lifecycle — `mt5_agent_realtime_lifecycle.md` extended with the sidecar topology and execution modes; connection states and reconnect flow already present.
- Execution lifecycle — command → `execution.ack` → `execution.report`, per mode (`observe`/`paper`/`live`); `observe` replies `SIMULATED`.
- Idempotency/retry/reconciliation — dedupe by command `id`, refuse past `expiresAt`, snapshot-before-trust on reconnect.
- EA mapping — 7-component split (`MarketDataPublisher`, `AccountStatePublisher`, `ExecutionCommandReceiver`, `OrderExecutor`, `ExecutionReporter`, `LocalRiskGuard`, `ConnectionSupervisor`) bound to modes and the sidecar.
- Recorded in ADR 0005.

This phase is documentation + wire contracts only; the EA (MQL5), sidecar, and gateway (.NET) are not built in this repo yet.

## Closure (2026-07-08)

Closed on 2026-07-08, reviewed together with Phases 01 and 02. All acceptance criteria met (contracts, session lifecycle, execution lifecycle, idempotency/retry/reconciliation, EA mapping). All deliverable artifacts confirmed present; `mt5-wire.ts` still passes lint + typecheck. At closure the user fixed the outstanding open question on gateway location: the WebSocket Gateway waits for the ASP.NET Core backend — no throwaway Node/Next WebSocket dev server will be built.
