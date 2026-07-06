# Dashboard Realtime Model

## Purpose

The dashboard should behave like a live trading cockpit.

It should subscribe to realtime streams and render the latest known state, not repeatedly poll REST endpoints.

## Connection States

Every screen using live data should be able to show:

- `mock`
- `connecting`
- `connected`
- `reconnecting`
- `stale`
- `degraded`
- `disconnected`
- `error`

## Subscription Groups

Initial dashboard subscriptions:

- account summary
- equity/drawdown
- open positions
- pending orders
- risk state
- market context
- strategy signals
- execution agent status
- alerts

## Snapshot + Events Pattern

Preferred frontend data pattern:

1. Connect to realtime gateway.
2. Request or receive initial snapshot.
3. Apply incoming events to local state.
4. Mark data stale when heartbeat is missed.
5. Request snapshot resync after reconnect.

## Mock Mode

Until backend exists, mock realtime should imitate the same pattern:

- initial snapshot
- event stream
- connection status
- stale/disconnected simulation

This keeps frontend architecture aligned with future SignalR/WebSocket integration.

