# Phase 05 Design - Live Observe Prototype (MT5 → cockpit)

Status: validated by the user on 2026-07-08 (Python `MetaTrader5` producer; symbol XAUUSDm; local execution OK) and implemented the same day. Completion notes in `phase-05-live-observe-prototype.md`.

## Objective

Bring real Exness demo data into the cockpit in read-only `observe` mode to validate the whole connection chain end-to-end, with real M15 candles feeding the Phase 04 ICT/SMC engine. No orders sent, no credentials shared.

## Existing Context

- Seam ready: `RealtimeClient {start, stop}`, `CockpitStore` (`hydrate`/`apply`/`setConnectionState`), provider instantiates the client.
- Lean edge protocol already defined in `lib/contracts/mt5-wire.ts`.
- `Environment` already includes `"demo"` — the badge can read DEMO.
- Phase 04 engine consumes `Candle[]`.
- 2026-07-08 decision: the production gateway waits for ASP.NET Core. This prototype revisits that for observe-only (ADR 0007).

## Impact Analysis

- New browser-side client `LiveRealtimeClient` behind the existing seam; zero component rewrites (only an honesty change to the environment badge).
- Translation runs in the browser for the prototype (ADR 0007); the production path keeps a server-side .NET gateway (ADR 0005) + MQL5 EA/sidecar (Phase 03).
- Mock stays default; live is opt-in via `NEXT_PUBLIC_REALTIME_SOURCE=live`.
- Honest gaps: risk/signals/execution/drawdown-baseline not produced — empty/zero states.

## Proposed Architecture

```text
MT5 Terminal (Exness demo, logged in)
   │ MetaTrader5 Python API (local, no credentials)
tools/mt5-observer/mt5_observer.py  (READ-ONLY, observe, no order_send)
   │ ws://localhost:8765, lean JSON (mt5-wire.ts)
lib/realtime/live-client.ts  →  lib/realtime/mt5-translate.ts (pure mappers)
   │ real M15 candles → lib/analysis (Phase 04) → Market Context
CockpitStore → panels (unchanged)
```

## Data Flow

Producer backfills `agent.hello` + account/positions snapshots + recent M15 candles, then loops: ticks (~1 Hz), account+positions (~2 s), heartbeat (~3 s), candle refresh (~15 s). `LiveRealtimeClient` drives `connecting→connected→stale→reconnecting`, translates via pure mappers into `store.hydrate`, and recomputes market context (debounced) from the candle window. No outbound messages.

## Files To Create Or Modify

Create: `lib/realtime/{mt5-translate.ts (+test), live-client.ts}`, `tools/mt5-observer/{mt5_observer.py, requirements.txt, README.md}`, `.env.example`, `context/adr/0007-live-observe-prototype.md`, `context/realtime/live_prototype.md`, this design + the phase file.
Modify: `lib/realtime/provider.tsx` (client selection), `components/shell/top-command-bar.tsx` (env-aware badge), project brain.

## Risks

- MetaTrader5 = Windows + terminal open/logged in (user's case).
- Exness symbol suffix `XAUUSDm` — configurable via `--symbol`.
- Browser translation = documented prototype debt (ADR 0007).
- Account fields not provided by MT5 shown as honest zeros, never as validated risk.
- `websockets` v12+ single-arg handler — pinned in requirements.

## Acceptance Criteria

See `phase-05-live-observe-prototype.md`.

## Implementation Checklist

1. [x] `mt5-translate.ts` pure mappers + tests.
2. [x] `LiveRealtimeClient` (WS, states, heartbeat watchdog, engine on candles).
3. [x] `provider.tsx` selection + DEMO badge.
4. [x] `mt5_observer.py` read-only producer + README + requirements.
5. [x] Verify lint / typecheck / build / test (+ `py_compile`).
6. [x] ADR 0007, `live_prototype.md`, phase files, project-brain updates.
7. [ ] User runs the producer against their demo and validates visually.
