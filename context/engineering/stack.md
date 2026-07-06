# Engineering Stack

## Current Repository

- Next.js 16.2.10
- React 19.2.4
- TypeScript
- Tailwind CSS 4
- ESLint

Read local Next.js documentation under `node_modules/next/dist/docs/` before assuming framework APIs.

## Recommended Frontend

- Next.js
- React
- TypeScript
- Tailwind CSS
- shadcn/ui
- TanStack Query
- React Hook Form
- Zod
- Recharts
- TradingView Lightweight Charts
- SignalR/WebSocket client as the primary data transport

## Recommended Backend

Target:

- ASP.NET Core
- C#
- SignalR as the primary realtime gateway
- Minimal APIs only for health, auth bootstrap, admin, imports, exports, and static snapshots
- Entity Framework Core
- Dapper for critical queries

## Recommended Infrastructure

- PostgreSQL for business data
- TimescaleDB for time-series market data
- Redis for cache/realtime state
- RabbitMQ for decoupled command/event flows
- Docker Compose for local development
- Serilog + Seq for logs
- Prometheus + Grafana for metrics

## Architecture Strategy

Begin as a modular monolith with strong boundaries.

Evolve toward microservices only when scaling, deployment, or team constraints justify extraction.

## Transport Strategy

Trading flows are WebSocket-first:

- market data streaming
- account state
- risk state
- market context
- strategy signals
- execution commands
- command acknowledgements
- execution reports
- alerts

Do not design the platform around REST polling.
