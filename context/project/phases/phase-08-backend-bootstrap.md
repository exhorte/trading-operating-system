# Phase 08 - ASP.NET Core Backend Bootstrap

Status: closed 2026-07-11 (implemented 2026-07-10, committed `0977175`; design in `phase-08-design.md`, validated first). **Validated live by the user** with the 3-terminal run: `/health` OK, cockpit DEMO + connected on the real Exness demo (account 436634705, equity $9,902.51), market context computed from real candles, honest observe-mode gates — translation now server-side in .NET. At closure the superseded `LiveRealtimeClient` (ADR 0007 browser shortcut) was deleted; `mt5-translate.ts` + tests remain as the TS reference the C# port mirrors.

## Objective

Stand up the real backend: .NET 10 host ingesting the lean MT5 wire via a WebSocket Gateway (server-side translation, superseding the Phase 05 browser shortcut), rebroadcasting to the cockpit over SignalR. Dashboard gains `SignalRRealtimeClient` behind the existing seam.

## Scope

In scope: `backend/` solution (Contracts mirrors, Gateway translator+client, Host hub+health), xUnit translator tests, frontend SignalR client + `backend` source, runbook.
Deferred (ADR 0009): DB, auth, Redis/RabbitMQ, C# engine ports, execution path, Docker; agent-dials-gateway direction (comes with the MQL5 agent).

## Acceptance Criteria

See `phase-08-design.md` — all code-level criteria met; the live end-to-end validation is the user's step (`context/backend/backend_bootstrap.md` runbook).

## Implementation Notes (2026-07-10)

Built `backend/TradingOs.slnx` (.NET 10): `TradingOs.Contracts` (Envelope, `Mt5*Message` records + `Mt5WireParser`, camelCase read models), `TradingOs.Gateway` (`Mt5WireTranslator` = C# port of `mt5-translate.ts`; `GatewayState`; `Mt5ObserverClient` WS client with auto-reconnect, read-only), `TradingOs.Host` (SignalR `CockpitHub` `/hub/cockpit` with `GetSnapshot` + `event` envelope broadcasts, `/health`, dev CORS, `GatewayBridgeService`), `tests/` (7 xUnit tests mirroring the TS translator tests 1:1).

Frontend: `lib/realtime/signalr-client.ts` (`SignalRRealtimeClient`: snapshot hydrate + event stream, heartbeat watchdog, initial-connect retry, TS engines on relayed candles + observe-mode risk), provider source `backend`, store gained the `agent.snapshot.positions` case, `@microsoft/signalr` added (first runtime dep), `.env.example` + `.gitignore` updated.

Verified: `dotnet build` 0 warnings/errors; `dotnet test` 7/7; host smoke test `/health` 200 + SignalR negotiate 200; frontend lint clean, source `tsc` exit 0, 47 Vitest tests.
