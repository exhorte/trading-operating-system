# Development Workflow

## Standard Flow

1. Load context.
2. Identify current phase.
3. Inspect existing code.
4. Produce impact analysis.
5. Design.
6. Implement incrementally.
7. Verify.
8. Update context.
9. Handoff.

## Realtime Flow Design

For market data, dashboard live state, execution, MT5 agent, or risk alerts, design the WebSocket/SignalR flow before implementation:

- connection owner
- subscription topic
- initial snapshot
- event types
- command/ack/report lifecycle
- reconnect/resync behavior
- failure states

## Phase Discipline

Do not let implementation outrun project memory.

Every phase should leave the repository easier for the next Claude session to understand.
