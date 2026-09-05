# Live Observe Prototype (Phase 05)

Read-only path that streams **real** MT5 demo data into the cockpit to validate
the full connection chain end-to-end. Decision + rationale in ADR 0007. Runbook
in `tools/mt5-observer/README.md`.

## Topology

```text
MT5 Terminal (Exness demo, already logged in on the user's machine)
   │  MetaTrader5 Python API (local IPC — no credentials)
tools/mt5-observer/mt5_observer.py     READ-ONLY, mode "observe", no order_send
   │  hosts ws://localhost:8765, emits lean JSON (lib/contracts/mt5-wire.ts)
lib/realtime/live-client.ts  (LiveRealtimeClient, implements RealtimeClient)
   │  lib/realtime/mt5-translate.ts  (pure lean → read-model mappers)
   │  real M15 candles → lib/analysis (Phase 04 engine) → Market Context
CockpitStore → panels (unchanged)
```

The browser-side translation is a **prototype shortcut** (ADR 0007). The
production path keeps a server-side .NET gateway (ADR 0005) and the MQL5 EA +
sidecar (Phase 03).

## Wire messages used (agent → cockpit only)

`agent.hello`, `account.snapshot`, `positions.snapshot`, `market.tick`,
`market.candle` (M15), `agent.heartbeat`. No commands are ever sent downstream.

## What is real vs. not

| Panel / field | Source in the prototype |
| --- | --- |
| Account balance, equity, currency | **Real** (MT5 `account_info`) |
| Daily P&L | Floating P&L (`equity − balance`) — real number, intraday approximation |
| Open positions, floating P&L, SL/TP | **Real** (MT5 `positions_get`) |
| XAUUSD ticks / current price | **Real** (MT5 `symbol_info_tick`) |
| Market context (bias, structure, liquidity, FVG/OB, score) | **Computed** by the Phase 04 engine from **real** M15 candles |
| Agent health / heartbeat / latency | Real connection + heartbeat |
| Daily drawdown %, total drawdown %, open-risk % | **0** — no risk engine / day baseline yet |
| Risk gates, signals, execution reports, P&L calendar | Honest empty states — engines don't exist yet |

## Enabling it

```bash
# terminal 1 — producer (Windows, MT5 open & logged in)
cd tools/mt5-observer && pip install -r requirements.txt
python mt5_observer.py --symbol XAUUSDm

# terminal 2 — cockpit in live mode (mock is the default otherwise)
$env:NEXT_PUBLIC_REALTIME_SOURCE="live"; npm run dev   # PowerShell
```

Config: `NEXT_PUBLIC_REALTIME_SOURCE` (`mock` default | `live`),
`NEXT_PUBLIC_MT5_WS_URL` (default `ws://localhost:8765`). See `.env.example`.

## Connection lifecycle

`connecting` → `connected` on socket open → `stale` if no heartbeat for ~8 s →
`reconnecting` on socket close (retry every 3 s). Same state machine the
`MockRealtimeClient` exercises, so the ConnectionBadge behaves identically.

## Safety

Producer is strictly read-only (no `order_send`, no trade calls). Execution
controls in the cockpit stay inert. No credentials are used or accepted.
