# Project State

## Current Status

The repository is a fresh Next.js project named `trading_operating_system_algorithmique`.

Initial project brain has been created from the source notes in `../NOTES/`.

The project brain has since been refined with:

- a WebSocket/SignalR-first architecture decision
- realtime event/command/report contracts
- MT5 agent realtime lifecycle guidance
- dashboard realtime subscription guidance
- visual reference analysis from `context/templates/`
- final interface specification for the trading cockpit

## Active Product Direction

Build a Trading Operating System Algorithmique where:

- Next.js provides the dashboard/control cockpit.
- Backend services will host the trading intelligence.
- WebSocket/SignalR is the primary communication infrastructure.
- The ICT/SMC framework becomes a reusable analysis engine.
- The MT5 EA becomes an execution and telemetry agent.
- FTMO-style risk controls are core constraints.

## Current Phase

Phase 00 - AI Project Brain Bootstrap: closed 2026-07-06.

Phase 01 - Frontend Foundation: implemented 2026-07-06 after validated design (`project/phases/phase-01-design.md`). The cockpit shell, Command Center, typed contracts, and mock realtime client exist; lint and build pass. Only a user visual walkthrough remains before declaring it fully closed.

Phase 02 - Domain Model MVP: implemented 2026-07-07 (`project/phases/phase-02-design.md`). Canonical portable schemas live in `lib/domain/`; `lib/contracts/` became the wire layer with full `EventPayloadMap` coverage; ADR 0004 records TypeScript as the MVP schema source. Lint, typecheck, and build pass with zero UI changes. Awaiting user review before closure (together with the Phase 01 visual walkthrough).

Phase 03 - MT5 Agent Spec: specified 2026-07-07 (`project/phases/phase-03-design.md`). Deliverables: `context/realtime/mt5_wire_protocol.md`, `lib/contracts/mt5-wire.ts`, extended `mt5_agent_realtime_lifecycle.md`, ADR 0005. This is documentation + wire contracts only; the EA/sidecar/gateway are not built here. Awaiting user review before closure.

## Next Up

Build the first realtime prototype against the Phase 03 spec: a WebSocket Gateway plus a mock/sidecar producer that speaks the lean MT5 wire protocol (`mt5-wire.ts`) in `observe` mode, wired end-to-end into the existing cockpit (dashboard side stays on the mock client / future SignalR). Decide where the gateway lives (a Node/Next WebSocket dev server now, or wait for the ASP.NET Core backend). Alternatively, close out Phases 01-03 with a user review first.

## Decisions Already Made

- The platform is not EA-centric.
- MT5 is the first execution connector.
- The EA in `../NOTES/Ultimate_ICT_Gold_Scalper_v4.0.mq5` is a base to analyze, personalize, refactor, and later transform into an agent.
- Next.js is the initial repository surface.
- Long-term backend target is ASP.NET Core with SignalR.
- The platform is WebSocket-first; REST/HTTP is secondary for auth/bootstrap/health/admin workflows only.
- PostgreSQL/TimescaleDB/Redis/RabbitMQ are preferred infrastructure candidates.
- The final interface direction is a dark, dense, operational trading cockpit.
- Visual references are inspiration only and must not be copied as TradeZella clones.
- Phase 01 must model UI data as mock realtime subscriptions, not REST polling.
- Phase 01 shipped with zero new runtime dependencies; shadcn/ui, TanStack Query, and chart libraries are deferred until their first real use case (validated 2026-07-06).
- UI components depend on the `RealtimeClient` seam and `CockpitStore`, never on the mock client directly.
- Canonical domain schemas are portable TypeScript in `lib/domain/` (ADR 0004); `lib/contracts/` is the wire layer and may depend on the domain, never the reverse.
- Dashboard read models (`lib/contracts/snapshots.ts`) are projections for rendering, not domain models; both are legitimate payloads on different channels.
- MT5 edge uses lean WSS+versioned JSON, not SignalR; a WebSocket Gateway translates it to the internal envelope. SignalR is dashboard-side only (ADR 0005).
- The MT5 agent connects through an external sidecar bridge (EA never opens the WSS socket directly); execution runs in `observe`/`paper`/`live` modes, `observe` never touching the broker.

## Open Questions

- Will this remain a single repository containing frontend, backend, EA, and infrastructure, or will the backend live in a sibling repository later?
- Which auth approach will be selected first: local auth, Supabase Auth, Auth0, or Keycloak?
- Will first market data be mocked, imported from MT5, or pulled from a market data provider?
- Which symbol set is MVP: XAUUSD only, or XAUUSD plus EURUSD/GBPUSD/USDJPY?
- Where does the WebSocket Gateway first run: a Node/Next WebSocket dev server for local development, or wait for the ASP.NET Core backend? (The MT5-edge transport itself is settled — lean WSS+JSON via ADR 0005; SignalR is dashboard-side only.)
- MVP symbol and account scope for the first agent prototype: XAUUSD single account is the working default, not yet formally confirmed.
