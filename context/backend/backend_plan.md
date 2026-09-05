# Backend Plan

## Purpose

The backend will become the platform brain.

## Target Modules

- Realtime Gateway
- Minimal HTTP Bootstrap
- Identity
- Market Data
- ICT/SMC Analysis
- Strategy
- Risk
- Portfolio
- Execution
- Analytics
- Notifications

## WebSocket-First Realtime

Use SignalR/WebSocket as the primary infrastructure for:

- MT5 agent sessions
- tick and candle streams
- market context updates
- risk state updates
- strategy signal updates
- position updates
- execution commands
- execution reports
- alerts

Avoid request/response polling for trading flows.

## Minimal HTTP Surface

HTTP can exist for:

- health checks
- login/auth bootstrap
- static configuration fetch
- historical exports/imports
- admin-only maintenance actions

## Rule

Backend owns decisions. Execution agents execute approved commands.
