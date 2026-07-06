# Development Manifesto

## Product Identity

This project is a Trading Operating System Algorithmique.

It is not:

- a quick EA
- a one-file trading bot
- a dashboard-only app
- a strategy backtest toy

It is a long-term platform designed to coordinate market data, ICT/SMC analysis, strategy decisions, risk controls, execution agents, analytics, and eventually AI-assisted optimization.

## First Principles

1. Platform over script.
2. Server intelligence over terminal intelligence.
3. Clean boundaries over fast coupling.
4. Explainability over black-box decisions.
5. Risk survival over profit promises.
6. Backtest and forward-test before confidence.
7. Modularity before premature microservices.
8. Documentation as project memory, not decoration.
9. WebSocket-first communication over request/response polling for trading flows.

## Trading Principles

- No martingale.
- No dangerous grid recovery.
- No unlimited averaging.
- Every position must have explicit risk, invalidation, stop, target logic, and audit trail.
- Daily loss, total drawdown, consecutive loss, news, spread, volatility, and session constraints are safety gates.
- Performance targets such as 11-15% monthly or FTMO completion in 20-30 days are hypotheses, never guarantees.

## Engineering Principles

- Prefer DDD and Clean Architecture for domain logic.
- Start with a modular monolith and extract services only when operationally justified.
- Keep domain models independent from UI, broker APIs, and infrastructure.
- Make strategy decisions reproducible from stored market context and configuration.
- Every integration with MT5 must handle disconnection, retries, duplicate messages, broker constraints, and reconciliation.
- Realtime flows must be modeled as events, commands, acknowledgements, and reports, not ad hoc HTTP calls.
- Update context documents after meaningful architecture or domain changes.

## Claude Behavior

Claude must act as a lead engineer:

- read context first
- analyze impact
- design before code for major work
- implement incrementally
- verify changes
- update memory and handoff
