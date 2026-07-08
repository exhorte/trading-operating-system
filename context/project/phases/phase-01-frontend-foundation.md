# Phase 01 - Frontend Foundation

## Objective

Build the first usable dashboard shell for the Trading Operating System Algorithmique.

## Scope

Create a professional cockpit foundation for:

- account overview
- equity and drawdown
- active positions
- risk status
- market context
- strategy signals
- execution status
- alerts

Use mock data only until backend contracts are formalized.

## Inputs

- `architecture/system_overview.md`
- `engineering/stack.md`
- `domain/trading_ontology.md`
- `domain/risk_ftmo.md`
- `frontend/visual_reference_analysis.md`
- `frontend/final_interface_spec.md`
- `realtime/dashboard_realtime_model.md`

## Deliverables

- responsive Next.js app shell
- dashboard homepage
- reusable UI sections
- typed mock data contracts
- mock realtime WebSocket event contracts
- basic visual language for trading cockpit
- first-pass command center layout based on the final interface spec

## Acceptance Criteria

- `npm run lint` passes.
- `npm run build` passes if implementation changes product code.
- UI does not pretend to be connected to live trading.
- Mock data is clearly separated from future realtime contracts.
- UI state is designed around event streams: connected, reconnecting, stale, disconnected, and degraded.
- Empty/loading/error states are represented.
- Visual design follows `frontend/final_interface_spec.md`.
- The app does not copy TradeZella branding or exact proprietary layouts.

## Notes For Claude

Next.js version is newer than model training expectations. Read `node_modules/next/dist/docs/` before making framework-specific assumptions.

## Completion Status

Implemented on 2026-07-06 after design validation (`phase-01-design.md`).

Delivered:

- `(cockpit)` route group: Command Center plus 9 stub screens with honest empty states, `loading.tsx`, `error.tsx`
- app shell: icon rail, collapsible sidebar, top command bar with MOCK badge, WebSocket status badge, inert emergency stop
- `lib/contracts/`: envelope, event types, and dashboard read models mirroring `realtime/event_contracts.md`
- `lib/realtime/`: `RealtimeClient` seam, `CockpitStore` (snapshot + events reducer), `MockRealtimeClient` with heartbeats, watchdog-driven stale detection, scripted outage/reconnect/resync cycle, React provider with `useSyncExternalStore`
- `lib/mock/`: enveloped mock generators (XAUUSD / FTMO-style account)
- 8 Command Center panels: KPI strip, risk status, market context, signal queue, agent health, positions table, P&L calendar, execution reports
- dark cockpit theme tokens in `globals.css`, zero new runtime dependencies

Verified:

- `npm run lint` and `npm run build` pass (11 routes).
- Production server smoke test: home page renders all panels; stub pages render empty states.
- Connection lifecycle (connected → stale → reconnecting → resync) is scripted in `MockRealtimeClient`; observe it with `npm run dev` on the WS badge (~40s cycle).

Remaining open:

- Visual walkthrough by the user in `npm run dev` (client-side lifecycle was verified by code and SSR smoke test, not by a browser session).

## Closure (2026-07-08)

Closed on 2026-07-08. The user elected to review and close Phases 01–03 together; that decision stands as the review sign-off, discharging the visual-walkthrough item above. Re-verified at closure: `npm run lint` clean, `tsc --noEmit` exit 0, `npm run build` compiles (13 static routes). All acceptance criteria met.
