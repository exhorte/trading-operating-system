# Project Memory

## Durable Facts

- Project name: Trading Operating System Algorithmique.
- Current repository: fresh Next.js app.
- Primary domain: algorithmic trading platform.
- First execution target: MT5 through MQL5 EA agent.
- Initial strategy inspiration: ICT/SMC Gold scalping, Silver Bullet, sweep/MSS/FVG/OB model.
- Core safety model: FTMO-style risk and drawdown constraints.
- Primary transport model: WebSocket/SignalR-first for trading flows.
- REST/HTTP role: secondary only for health, auth/bootstrap, static configuration, imports/exports, reports, and admin.
- Visual direction: dark, dense, risk-first trading cockpit inspired by visual references in `context/templates/`.
- Interface priority: realtime status, risk state, MT5 agent health, ICT/SMC market context, signals, execution reports, and auditability.

## Design North Star

Build the framework that lets many strategies, accounts, and execution connectors operate through the same governed platform.

## Recent History

2026-07-06:

- Created the initial `.claude/` and `context/` project brain.
- Analyzed the source notes and MQL5 EA.
- Decided the EA is a future execution/telemetry agent, not the platform brain.
- Adapted architecture to WebSocket/SignalR-first infrastructure.
- Added realtime contracts and MT5 agent lifecycle documents.
- Analyzed visual inspiration files and created the final interface specification.
- Audited and closed Phase 00; committed the project brain to git; renamed visual reference images to `reference-*` names. Phase 01 (frontend foundation, design first) is the active phase.

## Avoid

- turning the EA into the whole system
- building live trading before contracts and risk gates
- mixing domain logic inside UI components
- presenting performance claims as validated facts
- designing market-time UI around REST polling
- copying TradeZella branding or exact proprietary layouts
