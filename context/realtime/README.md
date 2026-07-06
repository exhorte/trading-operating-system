# Realtime Context

This directory defines the WebSocket-first infrastructure for the Trading Operating System Algorithmique.

Read this before designing dashboard data flows, MT5 agent flows, execution commands, market data streaming, or backend contracts.

## Core Rule

Trading flows are realtime-first.

REST/HTTP is secondary and limited to non-market-time operations.

## Files

- `websocket_first_architecture.md` - system-level realtime architecture.
- `event_contracts.md` - event envelopes, command contracts, acknowledgements, reports.
- `mt5_agent_realtime_lifecycle.md` - connection and execution lifecycle for MT5.
- `dashboard_realtime_model.md` - frontend subscription model.

