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

## Next Up

Phase 03 - MT5 Agent Spec: specify the MT5 EA agent's realtime lifecycle (connect, auth, snapshot, heartbeat, command handling, reconciliation) against the Phase 02 schemas — see `project/phases/phase-03-mt5-agent-spec.md`. Alternatively, resolve the open question on the first realtime prototype (plain WebSocket in Node/Next vs waiting for ASP.NET Core SignalR) before agent work begins.

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

## Open Questions

- Will this remain a single repository containing frontend, backend, EA, and infrastructure, or will the backend live in a sibling repository later?
- Which auth approach will be selected first: local auth, Supabase Auth, Auth0, or Keycloak?
- Will first market data be mocked, imported from MT5, or pulled from a market data provider?
- Which symbol set is MVP: XAUUSD only, or XAUUSD plus EURUSD/GBPUSD/USDJPY?
- Should the first realtime prototype use plain WebSocket in Node/Next for local development, or wait for the ASP.NET Core SignalR backend?
