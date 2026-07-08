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

Phase 01 - Frontend Foundation: closed 2026-07-08. Implemented 2026-07-06 after validated design (`project/phases/phase-01-design.md`). The cockpit shell, Command Center, typed contracts, and mock realtime client exist. The user's review-and-close decision discharged the last-open visual walkthrough.

Phase 02 - Domain Model MVP: closed 2026-07-08. Implemented 2026-07-07 (`project/phases/phase-02-design.md`). Canonical portable schemas live in `lib/domain/`; `lib/contracts/` became the wire layer with full `EventPayloadMap` coverage; ADR 0004 records TypeScript as the MVP schema source. Zero UI changes.

Phase 03 - MT5 Agent Spec: closed 2026-07-08. Specified 2026-07-07 (`project/phases/phase-03-design.md`). Deliverables: `context/realtime/mt5_wire_protocol.md`, `lib/contracts/mt5-wire.ts`, extended `mt5_agent_realtime_lifecycle.md`, ADR 0005. Documentation + wire contracts only; the EA/sidecar/gateway are not built here.

Phases 01-03 were reviewed and closed together on 2026-07-08. Re-verified at closure: `npm run lint` clean, `tsc --noEmit` exit 0, `npm run build` compiles (13 static routes); all deliverable artifacts confirmed present.

Phase 04 - ICT/SMC Engine MVP: closed 2026-07-08 (committed `298480a`; `project/phases/phase-04-design.md`). Pure TypeScript analysis engine in `lib/analysis/` (imports only `lib/domain`): swings → structure (BOS/CHOCH) → liquidity → PD arrays (FVG/OB) → session → bias → weighted scoring → `MarketContextState`; projection in `lib/contracts/projections.ts`. Validated on both mock and (Phase 05) real candles. Engine is v0.1 — a hypothesis, not a validated edge.

Phase 05 - Live Observe Prototype: closed 2026-07-08 (committed `4f56064`; `project/phases/phase-05-design.md`). Read-only path streaming **real** Exness demo data into the cockpit. `tools/mt5-observer/mt5_observer.py` (Python `MetaTrader5`, read-only, `observe`) emits lean `mt5-wire` JSON over `ws://localhost:8765`; `lib/realtime/live-client.ts` translates it via pure mappers (`lib/realtime/mt5-translate.ts`) and feeds real M15 candles to the Phase 04 engine. Opt-in via `NEXT_PUBLIC_REALTIME_SOURCE=live` (mock default); badge reads DEMO. Browser-side translation is a documented prototype shortcut (ADR 0007). **Validated live** by the user (account 436634705, XAUUSDm). KpiStrip fixed to degrade gracefully when `risk` is null.

## Next Up

**Phase 06 - Risk & Prop Firm Mode** (in phase-start): pure TS risk services (engine-first pattern, against `lib/domain/risk.ts`) computing risk state from account + positions + a `RiskPolicy` — daily loss, max drawdown, risk-per-trade, consecutive losses, target lockout, news/spread/session gates. Fills the currently-empty Risk Status panel and the "—" risk KPI tiles, in both mock and live. Unblocked by the backend. Later: ASP.NET Core backend to move gateway/translation server-side (replacing the prototype shortcut).

The engine-first, backend-later pattern (build pure domain engines in TS now, port to .NET when the backend arrives) is working well.

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
- The WebSocket Gateway waits for the ASP.NET Core backend; no throwaway Node/Next WebSocket dev server will be built (decided 2026-07-08). The first realtime prototype is therefore gated on standing up that backend surface.
- Domain engines are built as pure TypeScript in this repo now (against `lib/domain/`), imports-only-`lib/domain`, and ported to .NET when the backend arrives — the ICT/SMC engine (`lib/analysis/`, ADR 0006) is the first; risk services follow the same pattern. This unblocks server intelligence without waiting for infrastructure.
- Detectors obey a no-look-ahead invariant (a bar's state uses only candles up to that bar) to keep future backtests honest.
- Vitest is the domain test runner (dev-only, ADR 0006); runtime dependencies remain zero. Domain logic ships with deterministic-fixture unit tests.
- Live MT5 access uses a local read-only reader attached to the user's already-authenticated terminal (Python `MetaTrader5`) — **no credentials are ever shared**. The observe prototype's lean→internal translation runs browser-side as a documented, throwaway shortcut (ADR 0007); production keeps a server-side .NET gateway (ADR 0005) + MQL5 EA/sidecar (Phase 03). This carve-out applies to the prototype only; the 2026-07-08 "gateway waits for ASP.NET Core" decision still governs the production path.
- Read-only / `observe` is the mandatory mode for any first connection: no order path, execution controls stay inert.

## Open Questions

- Will this remain a single repository containing frontend, backend, EA, and infrastructure, or will the backend live in a sibling repository later?
- Which auth approach will be selected first: local auth, Supabase Auth, Auth0, or Keycloak?
- Will first market data be mocked, imported from MT5, or pulled from a market data provider?
- Which symbol set is MVP: XAUUSD only, or XAUUSD plus EURUSD/GBPUSD/USDJPY?
- MVP symbol and account scope for the first agent prototype: XAUUSD single account is the working default, not yet formally confirmed.

Resolved 2026-07-08: the WebSocket Gateway waits for the ASP.NET Core backend (no interim Node/Next dev server) — see Decisions Already Made.
