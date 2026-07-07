# Project Memory

## Durable Facts

- Project name: Trading Operating System Algorithmique.
- Current repository: Next.js cockpit surface with the platform's domain schemas and wire contracts (Phases 01-03 delivered); backend, EA, sidecar, and gateway are not built here yet.
- Primary domain: algorithmic trading platform.
- First execution target: MT5 through MQL5 EA agent.
- Initial strategy inspiration: ICT/SMC Gold scalping, Silver Bullet, sweep/MSS/FVG/OB model.
- Core safety model: FTMO-style risk and drawdown constraints.
- Primary transport model: WebSocket/SignalR-first for trading flows. The MT5 edge specifically uses lean WSS + versioned JSON translated by a WebSocket Gateway (SignalR is dashboard-side only) — ADR 0005.
- Canonical schemas: portable TypeScript in `lib/domain/`; `lib/contracts/` is the wire layer; the MT5 lean edge protocol is `lib/contracts/mt5-wire.ts` — ADR 0004/0005.
- Execution safety: server-side risk approval precedes execution; the agent runs in `observe`/`paper`/`live` modes, `observe` never touching the broker.
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
- Audited and closed Phase 00; committed the project brain to git; renamed visual reference images to `reference-*` names.
- Designed (user-validated) and implemented Phase 01: cockpit shell, Command Center with 8 panels, typed realtime contracts, mock realtime client with scripted outage cycle, zero new dependencies.

2026-07-07:

- Designed and implemented Phase 02 (Domain Model MVP): canonical portable schemas in `lib/domain/`, `lib/contracts/` promoted to the wire layer with exhaustive `EventPayloadMap`, ADR 0004 (TypeScript as MVP schema source). No UI change; lint/typecheck/build pass.
- Designed and specified Phase 03 (MT5 Agent Spec) from three user decisions (ADR 0005): lean WSS+versioned-JSON MT5 edge translated by a WebSocket Gateway; full command loop gated by `observe`/`paper`/`live` execution modes; external sidecar bridge for MQL5. Deliverables: `mt5_wire_protocol.md`, `lib/contracts/mt5-wire.ts`, lifecycle extension. Documentation + contracts only.
- Recorded this session in project memory as "platform-trading". Next: build the first WebSocket Gateway + mock sidecar producer speaking the lean protocol in `observe` mode, once the gateway's first home (Node/Next dev server vs ASP.NET Core) is chosen.

## Avoid

- turning the EA into the whole system
- building live trading before contracts and risk gates
- mixing domain logic inside UI components
- presenting performance claims as validated facts
- designing market-time UI around REST polling
- copying TradeZella branding or exact proprietary layouts
