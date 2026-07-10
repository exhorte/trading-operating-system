# Backend Bootstrap (Phase 08) — Runbook

The ASP.NET Core backend (`backend/`, .NET 10) ingests the lean MT5 wire from
the local observer, translates it server-side, and rebroadcasts to the cockpit
over SignalR. Decision record: ADR 0009. Observe-only and stateless.

## Topology

```text
MT5 terminal (logged in)
  → tools/mt5-observer/mt5_observer.py     (ws://localhost:8765, read-only)
  → TradingOs.Gateway (WS client)          lean JSON → C# translation
  → CockpitHub (SignalR)                   http://localhost:5080/hub/cockpit
  → SignalRRealtimeClient (dashboard)      snapshot (GetSnapshot) + "event" envelopes
```

## Run the full backend path (3 terminals)

```powershell
# 1 — MT5 observer (MT5 open & logged in)
cd tools/mt5-observer
python mt5_observer.py --symbol XAUUSDm

# 2 — backend host
cd backend
dotnet run --project src/TradingOs.Host

# 3 — cockpit (repo root); .env.local:
#    NEXT_PUBLIC_REALTIME_SOURCE=backend
npm run dev
```

Check `http://localhost:5080/health` → `{"status":"ok"}`. The cockpit badge
should read **DEMO + connected**, with translation now happening in .NET.

## Configuration

| Setting | Default | Where |
| --- | --- | --- |
| `Cockpit:ObserverUrl` | `ws://localhost:8765` | Host appsettings / env |
| `Cockpit:DashboardOrigin` | `http://localhost:3000` | CORS |
| `NEXT_PUBLIC_BACKEND_HUB_URL` | `http://localhost:5080/hub/cockpit` | `.env.local` |

## Verify

```powershell
cd backend
dotnet build TradingOs.slnx
dotnet test TradingOs.slnx    # xUnit translator tests mirror mt5-translate.test.ts
```

## Scope / not yet

Engines (ICT/SMC, risk) still run in TypeScript in the browser on relayed
candles/state; signals remain mock-only. No DB, auth, or execution path — see
ADR 0009 deferred list. The gateway dials the observer (prototype direction);
the real MQL5 agent will dial the gateway instead (ADR 0005).
