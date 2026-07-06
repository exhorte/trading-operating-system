# ADR 0003 - WebSocket-First Infrastructure

## Status

Accepted

## Context

The project originally referenced REST/API and WebSocket options. The user clarified that the platform should use a WebSocket infrastructure instead of a classic API-centric architecture.

Trading flows require persistent, low-latency, bidirectional communication:

- market data
- market context
- risk updates
- execution commands
- command acknowledgements
- execution reports
- MT5 agent health
- dashboard live state

## Decision

The platform is WebSocket-first.

SignalR/WebSocket will be the primary transport for trading flows.

REST/HTTP is allowed only for secondary workflows:

- health checks
- authentication/bootstrap
- static configuration snapshots
- imports/exports
- historical report downloads
- documentation
- admin workflows that do not require market-time state

## Consequences

- Dashboard architecture must be subscription-based.
- MT5 agent architecture must support persistent sessions.
- Execution commands must be idempotent and acknowledged.
- Reconnect/resync flows are mandatory.
- Event contracts become core platform artifacts.
- Backend target remains ASP.NET Core, but SignalR becomes the primary gateway rather than a side feature.

