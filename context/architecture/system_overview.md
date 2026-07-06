# System Overview

## Vision

The platform is a Trading Operating System Algorithmique.

It coordinates:

- dashboard
- realtime gateway
- market data
- ICT/SMC framework
- strategy engine
- risk engine
- portfolio engine
- execution engine
- MT5 connector
- analytics
- monitoring

## Target Flow

```text
Market / MT5 / Data Providers
        |
        v
Market Data Layer
        |
        v
Realtime Event Bus / SignalR Hubs
        |
        v
ICT/SMC Analysis Framework
        |
        v
Decision + Scoring + Risk Approval
        |
        v
Execution Engine
        |
        v
MT5 Agent -> MT5 Terminal -> Broker / Prop Firm
        |
        v
Execution Reports + Analytics + Dashboard
```

## Communication Model

The platform is WebSocket-first.

Primary realtime channels:

- Dashboard <-> Realtime Gateway
- MT5 Agent <-> Realtime Gateway
- Market Data <-> Analysis Engine
- Risk Engine <-> Dashboard
- Execution Engine <-> MT5 Agent
- Execution Reports <-> Analytics/Dashboard

REST/HTTP is not the main product communication path. It is allowed for:

- health checks
- authentication/bootstrap
- static configuration snapshots
- imports/exports
- documentation
- administrative workflows that do not require market-time state

## Layer Responsibilities

Data Layer:

- ticks
- candles
- spreads
- symbols
- sessions
- macro/news
- correlations

Analysis Layer:

- swings
- BOS/CHOCH/MSS
- liquidity
- FVG
- order blocks
- premium/discount
- SMT
- session context

Decision Layer:

- bias
- setup validation
- scoring
- strategy selection
- risk approval

Execution Layer:

- command creation as realtime messages
- broker constraint validation
- order routing
- retry and reconciliation
- fill reporting

Analytics Layer:

- trade rationale
- signal quality
- performance attribution
- drawdown
- replay
