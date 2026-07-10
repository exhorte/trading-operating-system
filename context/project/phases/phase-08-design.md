# Phase 08 Design - ASP.NET Core Backend Bootstrap

Status: validated by the user on 2026-07-10 (backend in this repo under `backend/`; minimal observe-only stateless slice) and implemented the same day. Completion notes in `phase-08-backend-bootstrap.md`.

## Objective

Stand up the real backend: an ASP.NET Core (.NET 10) host that ingests the lean MT5 wire through a WebSocket Gateway (replacing the Phase 05 browser-side translation, ADR 0007), translates to `Envelope<T>` + C# read-model mirrors (ADR 0004), and rebroadcasts to the cockpit over a SignalR hub. The dashboard gains a `SignalRRealtimeClient` behind the existing seam — third implementation, zero component changes.

## Existing Context

- ADR 0005 (two transport worlds, gateway translates), ADR 0007 (browser translation = throwaway), `backend_plan.md`/`stack.md` (ASP.NET Core, SignalR-first, minimal HTTP, modular monolith).
- Contracts ready: `mt5-wire.ts`, `Envelope<T>`/`EventPayloadMap`, pure mappers `mt5-translate.ts` (source for the C# port).
- Python observer (Phase 05) already speaks the lean wire and serves `ws://localhost:8765` — unchanged; the gateway dials it.
- Frontend seam `RealtimeClient {start, stop}` designed for this since Phase 01. `.NET 10 SDK` present on the user's machine.

## Impact Analysis

- New C# code under `backend/` (resolves the mono-repo open question). C# mirrors only for the slice's schemas; TS stays canonical (ADR 0004).
- Frontend: `signalr-client.ts` + `@microsoft/signalr` (first runtime dep — the target transport) + `NEXT_PUBLIC_REALTIME_SOURCE=backend`. Mock stays default; `LiveRealtimeClient` kept as fallback, slated for deletion.
- Engines stay TS client-side in this slice (candles relayed via hub; risk computed as in live mode). Deferred: DB/auth/Redis/RabbitMQ/C# engines/execution/Docker.

## Proposed Architecture

`backend/TradingOs.slnx`: `TradingOs.Contracts` (Envelope, Mt5Wire records + parser, read models), `TradingOs.Gateway` (`Mt5WireTranslator` port of mt5-translate, `GatewayState`, `Mt5ObserverClient` WS client with reconnect), `TradingOs.Host` (SignalR `CockpitHub` `/hub/cockpit` with `GetSnapshot`, `/health`, dev CORS, `GatewayBridgeService`), `tests/TradingOs.Gateway.Tests` (xUnit mirroring the TS translator tests).

## Data Flow

```text
observer (ws://8765) → Mt5ObserverClient → translate → GatewayState
  → GatewayBridgeService → CockpitHub broadcast "event" Envelope<T>
  → SignalRRealtimeClient: GetSnapshot hydrate + event stream
  → CockpitStore → panels (unchanged); TS engines on relayed candles/state
```

## Files To Create Or Modify

Create: `backend/` (slnx + 4 projects, ~10 C# files), `lib/realtime/signalr-client.ts`, ADR 0009, `context/backend/backend_bootstrap.md`, phase-08 files.
Modify: `lib/realtime/provider.tsx` (source `backend`), `lib/realtime/store.ts` (`agent.snapshot.positions` case), `package.json`, `.env.example`, `.gitignore` (bin/obj), brain.

## Risks

- Connection direction (gateway dials observer) is prototype-era; the MQL5 agent will dial the gateway later — isolated in `Mt5ObserverClient`.
- Two translators (TS+C#) until the TS one is deleted — mirrored tests keep them honest.
- First frontend runtime dependency — deliberate.
- `.slnx` (new solution format) — fine with SDK 10.

## Acceptance Criteria

- `dotnet build` + `dotnet test` green (translator tests mirror `mt5-translate.test.ts`).
- `/health` responds; SignalR negotiate 200.
- Full chain observer → gateway → SignalR → cockpit shows DEMO + connected with real data, translation server-side (user's live step).
- Frontend lint / source tsc / tests green; mock default; components untouched.
- ADR 0009 + runbook + brain updated.

## Implementation Checklist

1. [x] Scaffold solution/projects/references.
2. [x] Contracts (Envelope, Mt5Wire + parser, read models).
3. [x] Gateway (translator port, state, observer client).
4. [x] Host (hub + health + CORS + bridge).
5. [x] xUnit tests (7, mirroring TS cases).
6. [x] `dotnet build` + `dotnet test` green; host smoke test (/health 200, negotiate 200).
7. [x] Frontend: signalr client + provider + store case + env.
8. [x] Frontend lint/tsc/test green.
9. [x] ADR 0009, runbook, phase files, brain.
10. [ ] User: run the 3-terminal chain against MT5 and validate visually.
