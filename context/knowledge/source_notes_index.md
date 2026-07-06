# Source Notes Index

This file summarizes each source document from `../NOTES/` and explains how it should influence the platform.

## `framework ICT_SMC_PART_1.md`

Core lesson:

- Build a reusable ICT/SMC framework, not a monolithic EA.
- Separate analysis from strategy decision and execution.
- Represent market analysis as structured `MarketContext`.

Project impact:

- Create engines for price, swings, structure, liquidity, PD arrays, premium/discount, SMT, sessions, news, correlations, bias, scoring, entries, trade management, and analytics.
- Strategy modules should consume framework outputs instead of re-implementing raw detection logic.

## `framework ICT_SMC_PART_2.md`

Core lesson:

- Build a complete algorithmic trading platform.
- The EA is an execution agent connected to a server.
- The dashboard is a cockpit for monitoring, control, configuration, and explainability.

Project impact:

- Server owns decisions.
- MT5 owns local execution.
- WebSocket/SignalR-style realtime communication is the target.
- This target is now accepted as WebSocket-first architecture in `adr/0003-websocket-first-infrastructure.md`.
- Multi-account and multi-broker support must be anticipated from the beginning.

## `framework ICT_SMC_PART_3 STACK.md`

Core lesson:

- Use a professional stack: Next.js frontend, ASP.NET Core backend, SignalR, PostgreSQL, TimescaleDB, Redis, RabbitMQ, Docker, observability.
- Start modular and evolve toward services when justified.

Project impact:

- This repository begins as Next.js dashboard/bootstrap.
- Backend contracts should remain compatible with a future .NET implementation.
- Keep domain concepts portable across frontend, backend, and MQL5.

## `Description Configuration EA FTMO.md`

Core lesson:

- FTMO-style trading requires risk-first design.
- Profit targets are secondary to drawdown survival.
- Avoid grid and martingale.

Project impact:

- Risk engine is mandatory.
- Prop firm mode should include daily drawdown, total drawdown, max trades, session/news filters, and capital protection.
- Dashboard must expose risk state clearly.

## `Ultimate_ICT_Gold_Scalper_v4.0.mq5`

Core lesson:

- The EA already contains useful execution, risk, session, and ICT prototype logic.
- It is a strong source of domain details but should not define the final architecture.

Project impact:

- Extract the state machine and safety gates into documented platform concepts.
- Reuse MQL5 execution patterns for the MT5 agent.
- Move final strategy intelligence server-side over time.

## `chat1.md`

Core lesson:

- Reinforces the ICT/SMC framework approach and the separation between framework and strategy.

Project impact:

- Establishes `MarketContext` as the central analysis output.

## `chat2.md`

Core lesson:

- Establishes phase discipline and the AI Engineering Bootstrap style: context, manifesto, roadmap, phases, handoff, validation before implementation.

Project impact:

- The project must maintain `.claude/` and `context/` as durable development memory.

## `chat3.md`

Core lesson:

- Restates the project as a Trading Operating System and recommends a structured repository brain before code.

Project impact:

- Creates the foundation for this context structure and the Claude Code prompt.
