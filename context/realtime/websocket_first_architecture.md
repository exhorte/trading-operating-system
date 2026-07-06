# WebSocket-First Architecture

## Decision

The platform uses WebSocket/SignalR as the primary communication infrastructure.

This replaces the idea of a classic REST API as the main trading interface.

## Why

Trading systems need:

- low-latency state propagation
- persistent agent sessions
- server-pushed execution commands
- immediate risk alerts
- live dashboard updates
- connection supervision
- command acknowledgements
- execution reports

Polling a REST API for these workflows creates avoidable latency, duplicate state handling, and fragile execution loops.

## Primary Hubs

In the future ASP.NET Core backend, the preferred model is SignalR hubs:

- `MarketDataHub`
- `DashboardHub`
- `ExecutionHub`
- `RiskHub`
- `AnalyticsHub`
- `AgentHub`

These hubs may start as one `TradingHub` during early prototyping, then split when complexity justifies it.

## Main Connections

Dashboard connection:

```text
Next.js Dashboard
        |
        | WebSocket / SignalR
        v
Realtime Gateway
        |
        v
Market Context / Risk / Portfolio / Execution / Analytics
```

MT5 agent connection:

```text
MT5 EA Agent
        |
        | WebSocket
        v
Realtime Gateway
        |
        v
Execution Engine / Risk Engine / Market Data
```

Execution path:

```text
Strategy Signal
        |
        v
Risk Approval
        |
        v
Execution Command
        |
        v
WebSocket -> MT5 Agent
        |
        v
MT5 OrderSend
        |
        v
Execution Report -> WebSocket -> Server -> Dashboard/Analytics
```

## REST/HTTP Allowed Uses

HTTP remains acceptable for:

- health checks
- authentication/bootstrap
- static configuration snapshots
- file import/export
- historical report download
- admin maintenance operations
- documentation

HTTP should not be used for:

- tick streaming
- candle streaming
- live position updates
- execution command delivery
- execution reports
- risk alerts
- dashboard live state polling

## Reliability Requirements

Every realtime client must handle:

- authentication
- authorization
- connection id
- heartbeat
- reconnect
- stale state detection
- resubscription
- snapshot resync
- idempotent command handling
- duplicate message detection
- audit logging

## Message Direction

Server to Dashboard:

- market context updates
- signal updates
- risk updates
- position updates
- execution reports
- alerts

Dashboard to Server:

- subscribe/unsubscribe
- acknowledge alerts
- request snapshot resync
- configuration changes when authorized
- emergency stop when authorized

MT5 Agent to Server:

- heartbeat
- terminal state
- account state
- symbol metadata
- ticks/candles
- execution reports
- position snapshots

Server to MT5 Agent:

- execution commands
- modification commands
- close commands
- risk lockout commands
- resync requests

