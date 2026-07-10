# ADR 0009 - ASP.NET Core Backend Bootstrap (Observe Slice)

## Status

Accepted

## Context

ADR 0005 fixed the two transport worlds (lean WSS+JSON at the MT5 edge, SignalR dashboard-side, a .NET gateway translating between them); ADR 0007 allowed a browser-side translation as a deliberately throwaway prototype. Phases 04–07 built the engines and business flow in TypeScript. The user chose the backend as the next infrastructure step, with the flow stabilised first.

Decisions validated by the user (2026-07-10): the backend lives **in this repo** under `backend/` (modular monolith — resolves the mono-repo open question for now), and the phase ships the **minimal observe-only, stateless slice**: gateway + SignalR hub + dashboard client. No DB, no auth, no C# engine ports, no execution.

## Decision

`backend/TradingOs.slnx` (.NET 10), three projects + tests:

- **TradingOs.Contracts** — C# mirrors of the slice's schemas: `Envelope<T>`, lean `Mt5*Message` records + `Mt5WireParser` (type-discriminator dispatch), dashboard read models (camelCase JSON so the TS store consumes them unchanged). ADR 0004 applies: TS stays canonical; divergence is a defect.
- **TradingOs.Gateway** — `Mt5WireTranslator`, a C# port of `lib/realtime/mt5-translate.ts` (xUnit tests mirror the TS test cases 1:1); `GatewayState` (latest snapshot: account/positions/agent/candles); `Mt5ObserverClient`, a WS **client** dialing the Python observer (`ws://localhost:8765`), read-only, auto-reconnect.
- **TradingOs.Host** — ASP.NET Core: SignalR `CockpitHub` (`/hub/cockpit`, `GetSnapshot` + `event` envelope broadcasts — the documented snapshot+events pattern), `/health`, dev CORS for `localhost:3000`, `GatewayBridgeService` bridging gateway → hub. Listens on `http://localhost:5080`.

Frontend: `SignalRRealtimeClient` (`lib/realtime/signalr-client.ts`) behind the existing `RealtimeClient` seam — third implementation after mock and live; selected with `NEXT_PUBLIC_REALTIME_SOURCE=backend`. Mock stays the default. First frontend runtime dependency: `@microsoft/signalr` (the target transport since Phase 01).

Engines stay TypeScript in this slice: the client still runs ICT/SMC on relayed candles and the risk engine on account/positions (session baseline, honest "n/a"). Porting engines to C# is a later phase.

## Consequences

- The production path exists end-to-end: MT5 → observer → **.NET gateway (server-side translation)** → SignalR → cockpit. ADR 0007's browser-side shortcut is superseded; `LiveRealtimeClient` is kept as a fallback and slated for deletion once the backend path is validated live.
- Connection direction is prototype-era: the gateway **dials the observer** (which is a WS server today). The definitive MQL5 agent + sidecar will dial the gateway instead (ADR 0005); only `Mt5ObserverClient` changes.
- Two translators exist (TS + C#) with mirrored tests; keep both in sync until the TS one is deleted.
- Stateless by design: restart loses nothing but the in-memory snapshot; persistence (PostgreSQL/Timescale) arrives with a later phase.
- Deferred: auth, DB, Redis/RabbitMQ, C# engines, execution command path (Phase 09), Docker.
