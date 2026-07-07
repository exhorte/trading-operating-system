# MT5 Agent Realtime Lifecycle

## Purpose

Define how the MT5 EA agent connects to the platform through WebSocket-first infrastructure.

Phase 03 (ADR 0005) fixed the concrete shape: the EA speaks lean versioned JSON (`context/realtime/mt5_wire_protocol.md`) to a local **sidecar bridge**, which holds the WSS connection to the **WebSocket Gateway**; the gateway translates to the internal `Envelope<T>`. Execution is gated by modes (`observe` → `paper` → `live`).

## Topology

```text
EA (MQL5)  ──named pipe / localhost socket──▶  Sidecar bridge  ──WSS──▶  WebSocket Gateway (.NET)  ──▶  Trading Engine
```

The sidecar is a dumb transport relay: it owns WSS framing, heartbeat, and reconnect, and forwards lean JSON verbatim in both directions. No business logic lives in it, so MQL5 trading callbacks are never blocked on the network.

## Lifecycle

1. Start EA in MT5 terminal.
2. Load local configuration:
   - agent id
   - account id
   - server websocket URL
   - environment mode
   - auth token or credential reference
3. Connect to realtime gateway.
4. Authenticate.
5. Register capabilities:
   - symbol
   - account
   - broker
   - supported order types
   - volume min/max/step
   - filling mode
   - stops level
6. Send account and position snapshot.
7. Begin heartbeat.
8. Stream telemetry and market data as configured.
9. Receive execution commands only after server marks agent healthy.
10. Acknowledge each command.
11. Execute through MT5.
12. Report broker result.
13. Resync after disconnect or restart.

## Connection States

- `starting`
- `connecting`
- `authenticating`
- `registered`
- `healthy`
- `degraded`
- `reconnecting`
- `stale`
- `disabled`

## Local Safety Guards

The MT5 agent may enforce emergency local safety:

- trading disabled locally
- daily lockout command active
- unsupported symbol
- volume outside broker limits
- stops too close
- market closed
- account mismatch
- duplicate command
- stale connection

Local guards do not replace server-side risk approval.

## Reconnect Behavior

On reconnect:

1. Agent authenticates again.
2. Agent sends fresh account snapshot.
3. Agent sends fresh position snapshot.
4. Server reconciles open positions and pending commands.
5. Server decides whether execution is enabled.

No new execution command should be trusted until reconciliation completes.

## Notes For MQL5

MQL5 does not provide the same networking ergonomics as backend languages. During implementation, choose the safest available approach:

- native WebRequest is acceptable only for bootstrap/health fallback, not primary trading loop
- Phase 03 chose an external sidecar bridge (ADR 0005): the EA talks to a local process over a named pipe / localhost socket and never opens the WSS socket itself
- the agent must never busy-loop or block trading callbacks for long periods
- all command execution must remain auditable

## Execution Modes

Every command runs through the same `ExecutionCommandReceiver → LocalRiskGuard → OrderExecutor → ExecutionReporter` path; the mode only changes the terminal action (ADR 0005, `mt5_wire_protocol.md`).

- `observe` (default) — never sends to the broker; `OrderExecutor` replies `execution.report` with status `SIMULATED`. Validates protocol, ACKs, IDs, retries, timeouts, and reconnects at zero financial risk.
- `paper` — routes to a demo account; real broker statuses.
- `live` — routes to the FTMO broker; real broker statuses.

Only configuration changes between modes (`execution.enabled`, `execution.mode`). `LocalRiskGuard` treats an unknown or absent mode as `observe`. The backend Trading Engine mirrors this with an `ExecutionAdapter` (`NullExecution` / `PaperExecution` / `MT5Execution` / future `FIXExecution`) and never knows which is active.

