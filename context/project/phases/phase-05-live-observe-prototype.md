# Phase 05 - Live Observe Prototype (MT5 → cockpit, read-only)

Status: implemented 2026-07-08 (design in `phase-05-design.md`, validated by the user first: Python producer, symbol XAUUSDm, local execution OK). Awaiting the user's live run against their Exness demo before closure.

## Objective

Stream real Exness demo data (account, positions, ticks, M15 candles) into the cockpit in read-only `observe` mode to validate the full connection path — with real candles feeding the Phase 04 ICT/SMC engine. No orders, no credentials.

## Scope

In scope: Python `MetaTrader5` producer (read-only), lean-wire WebSocket, browser `LiveRealtimeClient` translating into `CockpitStore`, engine-computed market context on real candles, DEMO badge, opt-in via env (mock stays default).

Out of scope: any execution/command path, risk engine, signals, daily-drawdown baseline, the definitive MQL5 EA + sidecar and .NET gateway (those remain the production target — ADR 0005/0007).

## Acceptance Criteria

- With MT5 terminal + demo + producer running and `NEXT_PUBLIC_REALTIME_SOURCE=live`: real balance/equity, real positions, live XAUUSD ticks, badge **connected** + **DEMO**, agent heartbeat/latency, and a Market Context panel computed by the engine from real M15 candles.
- Producer is strictly read-only (no `order_send` / trade calls — verifiable by grep).
- Mock remains default; `lint` / `tsc` / `build` / `test` green; translation mappers unit-tested.
- ADR 0007 + `live_prototype.md` + phase files + brain updated.

## Implementation Notes (2026-07-08)

Built: `lib/realtime/mt5-translate.ts` (pure mappers + 6 tests), `lib/realtime/live-client.ts` (`LiveRealtimeClient`: WS, connection-state machine, heartbeat watchdog, candle window → engine), `provider.tsx` client selection by env, environment-aware badge in `top-command-bar.tsx` (MOCK/DEMO/PAPER/LIVE), `tools/mt5-observer/{mt5_observer.py, requirements.txt, README.md}`, `.env.example`, ADR 0007, `context/realtime/live_prototype.md`.

Verified here: lint clean, `tsc --noEmit` exit 0, build passes (13 routes), 29 Vitest tests (10 files); `python -m py_compile` OK on the producer. The real end-to-end run is the user's step (needs their Windows terminal + demo).

Honest gaps by design: risk/signals/execution/drawdown-baseline are not produced (engines don't exist) — shown as empty/zero, never as validated numbers. Browser-side translation is a documented prototype shortcut (ADR 0007), to be replaced by the .NET gateway + MQL5 agent.

## Closure (2026-07-08)

Closed 2026-07-08 (committed `4f56064`). **Validated live** by the user against their real Exness demo (account 436634705, XAUUSDm): badge DEMO + connected, real balance/equity/positions, live ticks, agent `mt5-observer-1`, and market context computed by the Phase 04 engine on real M15 candles. Fixed at closure: the KPI strip blanked entirely when `risk` was null (live mode) — now it degrades gracefully (real equity/positions/agents render; risk tiles show "—"). Gates green (lint, source `tsc`, build, 29 tests, `py_compile`).

Follow-up captured: the empty Risk Status panel + "—" risk tiles are exactly what Phase 06 (Risk & Prop Firm Mode) fills.
