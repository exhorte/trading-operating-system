# ADR 0005 - MT5 Lean WebSocket Wire, Gateway Translation, Sidecar, Execution Modes

## Status

Accepted

## Context

Phase 03 specifies the MT5 execution/telemetry agent. ADR 0003 made the platform WebSocket-first with ASP.NET Core SignalR as the primary gateway. But MQL5 has no maintained SignalR client: putting SignalR in the EA would mean hand-rolling negotiation, framing, and reconnection in a language with weak networking ergonomics that must never block trading callbacks. The agent also needs to be testable end-to-end before any real order is placed.

## Decision

1. **Two separate transport worlds.** At the MT5 edge the agent speaks secure WebSocket (WSS) with lean, versioned JSON (`lib/contracts/mt5-wire.ts`). SignalR is used only between the backend and the Next.js dashboard. A **WebSocket Gateway** (.NET) translates the lean edge protocol into the internal `Envelope<T>` + Phase 02 domain models and back (mapping tables in `context/realtime/mt5_wire_protocol.md`).

2. **Lean edge envelope, enriched by the gateway.** The edge format is flat: `version`, `type`, `accountId`, epoch-ms `time`, command `id`, uppercase side, no correlation/causation. The gateway generates `messageId`, assigns `correlationId`/`causationId`, and reshapes flat fields into domain payloads. This is a deliberate two-layer design, not drift from Phase 02.

3. **External sidecar bridge for MQL5 networking.** The EA exchanges lean JSON with a local sidecar process (named pipe / localhost socket); the sidecar owns the WSS connection, framing, and reconnect. The sidecar is a dumb transport relay with no business logic, keeping MQL5 trading callbacks unblocked. Native `WebRequest` remains allowed only for bootstrap/health fallback, never the trading loop.

4. **Execution modes over identical command flow.** The full command loop ships from the first sprint gated by `observe` → `paper` → `live`. `observe` never sends to the broker and replies `SIMULATED`; only configuration changes between modes. The backend Trading Engine talks to an `ExecutionAdapter` abstraction (`NullExecution` / `PaperExecution` / `MT5Execution` / future `FIXExecution`) and never knows which is active. `LocalRiskGuard` treats an unknown/absent mode as `observe`.

## Consequences

- The EA stays simple (`Connect → Send → Receive → Reconnect`); protocol complexity lives in the gateway.
- A new deployable component exists: the sidecar bridge (per terminal/agent).
- The lean edge protocol is a second canonical wire contract (`mt5-wire.ts`) alongside the internal envelope; both mirror `lib/domain`. The gateway mapping is a documented translation, verified by review until code generation exists.
- The whole execution path — protocol, ACKs, IDs, retries, timeouts, reconnects — is testable at zero financial risk from week one via `observe` mode.
- Supersedes nothing; refines ADR 0003 for the MT5 edge specifically.
