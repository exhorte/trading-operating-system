# Phase 01 - Technical Design - Frontend Foundation

Status: validated by user on 2026-07-06 (zero-dependency option confirmed) and implemented the same day. See the phase file for completion notes.

## Objective

Build the first usable dashboard shell of the trading cockpit in Next.js 16 with:

- an app shell (icon rail, sidebar, top command bar) matching `frontend/final_interface_spec.md`
- a Command Center homepage rendering the first-viewport operational state
- typed mock data contracts mirroring `realtime/event_contracts.md`
- a mock realtime client that imitates the snapshot + events + heartbeat pattern
- dark-first cockpit visual language with semantic trading colors

No live trading, no backend, no REST polling. Everything is visibly mock.

## Existing Context

- Repository: fresh `create-next-app` (Next.js 16.2.10, React 19.2.4, TypeScript, Tailwind CSS 4, ESLint 9). Only `app/layout.tsx`, `app/page.tsx`, `app/globals.css` exist.
- Local Next.js docs confirmed: App Router conventions (`layout`/`page`/`loading`/`error` files, root layout with `html`/`body`, route groups) are as expected; no impact from Next 16 breaking changes on this phase's scope.
- Inputs honored: `architecture/system_overview.md`, `engineering/stack.md`, `governance/quality_gates.md`, `frontend/frontend_plan.md`, `frontend/final_interface_spec.md`, `frontend/visual_reference_analysis.md`, `realtime/dashboard_realtime_model.md`, `realtime/event_contracts.md`.

## Impact Analysis

- Replaces the create-next-app boilerplate homepage and global styles.
- Introduces the first product directories (`components/`, `lib/`) — these become the frontend conventions for all later phases.
- The TypeScript contracts written here are the seed of Phase 02 (Domain Model MVP); they must stay conceptually identical to `realtime/event_contracts.md` so Phase 02 can formalize rather than rewrite them.
- The `RealtimeClient` interface written here is the seam where the future SignalR/WebSocket client plugs in (Phase 03+); UI components must depend on the interface, never on the mock implementation.
- No backend, no infra, no EA impact.

## Proposed Architecture

### Route structure (App Router)

```text
app/
  layout.tsx                 root layout: fonts, theme, providers, CockpitShell
  (cockpit)/
    page.tsx                 / Command Center
    market-context/page.tsx  /market-context
    signals/page.tsx         /signals
    positions/page.tsx       /positions
    journal/page.tsx         /journal
    risk/page.tsx            /risk
    agents/page.tsx          /agents
    backtests/page.tsx       /backtests  (stub, empty state)
    replay/page.tsx          /replay     (stub, empty state)
    settings/page.tsx        /settings   (stub, empty state)
```

The Command Center is fully built in this phase. The other screens receive the shell, a title, and a designed empty state ("not yet implemented — Phase XX") so navigation is real but honest.

### Directory layout

```text
components/
  shell/        IconRail, Sidebar, TopCommandBar, EnvironmentBadge, ConnectionBadge
  cockpit/      KpiStrip, RiskStatusPanel, MarketContextPanel, SignalQueue,
                AgentHealthPanel, PositionsTable, PnlCalendar, ExecutionReportsFeed
  ui/           Card, Badge, StatusPill, DataTable, EmptyState, Skeleton, SectionHeader
lib/
  contracts/    TypeScript mirrors of realtime/event_contracts.md:
                envelope.ts, events.ts, snapshots.ts, enums.ts
  realtime/     client.ts (RealtimeClient interface + connection state machine),
                mock-client.ts (MockRealtimeClient), store.ts (useSyncExternalStore
                stores per subscription group), provider.tsx (React context)
  mock/         deterministic-ish generators: account, positions, signals,
                risk state, market context, agent heartbeats, execution reports
```

### Key design decisions

1. **Contracts-first**: `lib/contracts/` types copy the envelope (`messageId`, `correlationId`, `causationId`, `type`, `schemaVersion`, `source`, `target`, `sentAt`, `payload`) and the event families verbatim from `realtime/event_contracts.md`. Mock data is produced *as enveloped events*, not as ad hoc objects, so the UI consumes the same shape the future gateway will send.
2. **RealtimeClient seam**: components never import the mock directly. They use a `RealtimeProvider` + hooks (`useConnectionState()`, `useSubscription(group)`), backed by `useSyncExternalStore`. Swapping in SignalR later means one new class, zero UI changes.
3. **Connection state machine**: `mock → connecting → connected → reconnecting → stale → degraded → disconnected → error` as a typed union. The mock client cycles realistic transitions (including simulated stale/reconnect) so every state is exercised and visible in the ConnectionBadge.
4. **Snapshot + events**: the mock client emits an initial snapshot per subscription group, then a periodic event stream and heartbeats; missing heartbeats flip state to `stale`. This mirrors `realtime/dashboard_realtime_model.md` exactly.
5. **No new runtime dependencies in Phase 01**: no shadcn/ui, no TanStack Query, no chart library yet. Tailwind 4 primitives + `useSyncExternalStore` cover this phase; heavier libraries arrive when their first real use case does (charts in Market Context, forms in Settings). This keeps the phase reviewable and defers dependency choices to phases that need them.
6. **Dark-first theme as Tailwind 4 `@theme` tokens** in `globals.css`: background near-black, charcoal surfaces, soft borders, off-white text, semantic `profit`/`loss`/`warning`/`info`/`accent` colors, `tabular-nums` for all financial figures.
7. **Honest mock**: a persistent `MOCK` environment badge in the top command bar; no emergency-stop or execution buttons rendered as active — execution controls appear disabled with an explanatory tooltip state, per the "no fake live controls" rule.

## Data Flow

```text
MockRealtimeClient
  → emits Envelope<Event> per subscription group
    (account summary, positions, risk state, market context,
     signals, agent status, execution reports, alerts)
  → RealtimeStore (per group: snapshot + applied events + lastHeartbeat)
  → useSubscription(group) via useSyncExternalStore
  → cockpit panels render latest known state + connection state
  → heartbeat watchdog marks groups stale → panels show stale styling
```

## Files To Create

- `app/(cockpit)/…` pages listed above, plus `loading.tsx` and `error.tsx` for the group
- `components/shell/*` (5 components)
- `components/cockpit/*` (8 panels)
- `components/ui/*` (7 primitives)
- `lib/contracts/*` (4 files)
- `lib/realtime/*` (4 files)
- `lib/mock/*` (generators)

## Files To Modify

- `app/layout.tsx` — metadata, fonts, RealtimeProvider, shell
- `app/globals.css` — cockpit theme tokens, replace boilerplate
- `app/page.tsx` — moved/replaced by `(cockpit)/page.tsx` Command Center
- delete unused boilerplate assets in `public/` (create-next-app SVGs)

## Risks

- **Mock realism drift**: mock generators could drift from real MT5/broker semantics. Mitigation: generators only emit shapes defined in `lib/contracts/`, which mirror the documented contracts.
- **Premature UI polish**: the cockpit spec is large; over-building screens now wastes effort before Phase 02 contracts exist. Mitigation: only the Command Center is fully built; other screens are honest stubs.
- **Next 16 specifics**: docs confirmed conventions used here; anything framework-surprising during implementation gets checked against `node_modules/next/dist/docs/` before use.
- **Tailwind 4 theming**: `@theme` token syntax differs from Tailwind 3; verified against local Tailwind 4 setup during implementation.

## Alternatives Considered

- **shadcn/ui now**: rejected for this phase — adds many files/deps before forms/dialogs exist; revisit in the phase that needs form controls.
- **TanStack Query for realtime state**: rejected — it models request/response caching; our model is subscription streams. `useSyncExternalStore` matches the snapshot+events pattern directly.
- **Zustand/Redux**: unnecessary at this scale; the store is a thin typed wrapper the future SignalR client will reuse.

## Acceptance Criteria

From `phase-01-frontend-foundation.md`:

- `npm run lint` and `npm run build` pass.
- UI never pretends to be live: MOCK badge always visible, execution controls inert.
- Mock data separated (`lib/mock/`) from contracts (`lib/contracts/`).
- Connection states connected/reconnecting/stale/disconnected/degraded are all reachable and rendered.
- Empty/loading/error states exist (stub pages, `loading.tsx`, `error.tsx`, panel skeletons).
- Visual design follows `frontend/final_interface_spec.md`; no TradeZella branding or layout copies.

## Verification Plan

1. `npm run lint` and `npm run build`.
2. `npm run dev` — walk every nav route, verify shell persistence and empty states.
3. Observe the mock connection lifecycle in the ConnectionBadge (connected → stale → reconnecting → connected).
4. Verify KPI strip, risk panel, signal queue, positions table render mock snapshots and update on events.
5. Update `project_state.md`, `handoff.md`, `changelog.md`, and the phase file at closure.

## Implementation Checklist

1. Theme tokens + global styles (`globals.css`).
2. `lib/contracts/` types.
3. `lib/mock/` generators.
4. `lib/realtime/` client interface, mock client, store, provider, hooks.
5. `components/ui/` primitives.
6. `components/shell/` + root layout integration.
7. `(cockpit)` route group: Command Center panels, then stub pages.
8. Loading/error states.
9. Lint, build, manual walkthrough.
10. Memory updates + phase notes.
