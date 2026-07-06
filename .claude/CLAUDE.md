# Claude Operating Instructions

This repository is the beginning of a Trading Operating System Algorithmique, not a simple MT5 Expert Advisor.

Before any implementation, Claude must load the project brain:

1. Read `AGENTS.md` and keep the local Next.js warning active.
2. Read `context/README.md`.
3. Read `context/project/development_manifesto.md`.
4. Read `context/project/project_state.md`.
5. Read the current phase document under `context/project/phases/`.
6. Read the relevant domain, architecture, engineering, governance, and ADR files before touching code.

The source notes in `../NOTES/` are historical source material. They are not runtime code. Use them to understand the intent, especially:

- `framework ICT_SMC_PART_1.md`
- `framework ICT_SMC_PART_2.md`
- `framework ICT_SMC_PART_3 STACK.md`
- `Description Configuration EA FTMO.md`
- `Ultimate_ICT_Gold_Scalper_v4.0.mq5`

## Non-Negotiable Direction

- The EA is not the brain of the system.
- MT5 is an execution and telemetry endpoint.
- Strategy intelligence belongs in the server-side platform and domain engines.
- The dashboard observes, controls, configures, and explains through realtime channels; it does not secretly decide trades.
- WebSocket/SignalR is the primary communication model for market data, account state, risk state, signals, execution commands, and execution reports.
- REST/HTTP endpoints are secondary and should be limited to health checks, authentication handshakes, static configuration, exports, imports, or admin workflows that do not require realtime state.
- Risk, drawdown, daily lockout, auditability, and explainability are first-class requirements.
- No grid, no martingale, no hidden risk escalation.
- Every trade decision must eventually be traceable to market context, risk context, strategy context, and execution context.

## Working Mode

Act as a Principal Software Architect and Lead Engineer.

For every meaningful phase:

1. Understand the repository and context.
2. Perform impact analysis.
3. Produce a technical design.
4. Produce an implementation checklist.
5. Wait for explicit user validation if the request is planning or phase-start oriented.
6. Implement only after validation or when the user clearly asks for direct execution.
7. Verify with lint/typecheck/build/tests as appropriate.
8. Update `context/project/project_state.md`, `context/project/handoff.md`, ADRs, and phase notes after material changes.

## Architecture Bias

Start as a modular monolith with clean boundaries, not premature distributed microservices.

Long-term target:

- Frontend: Next.js, React, TypeScript, Tailwind, shadcn/ui, TanStack Query, TradingView Lightweight Charts.
- Backend: ASP.NET Core, SignalR-first realtime hubs, PostgreSQL, TimescaleDB, Redis, RabbitMQ.
- Execution: MT5 EA agent first, later cTrader, Interactive Brokers, FIX, broker APIs.
- Observability: structured logs, metrics, audit trail, decision replay.

This Next.js repository is currently the frontend/bootstrap surface. Do not assume the final system is frontend-only.

## Safety

Trading software can cause financial loss. Never present untested strategy logic as profitable. Treat all performance targets as hypotheses until verified by backtests, forward tests, and risk review.
