# MT5 Agent Realtime Lifecycle

## Purpose

Define how the MT5 EA agent connects to the platform through WebSocket-first infrastructure.

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
- a WebSocket library or bridge may be required
- the agent must never busy-loop or block trading callbacks for long periods
- all command execution must remain auditable

