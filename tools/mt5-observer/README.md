# MT5 Observer — read-only live prototype (Phase 05)

Streams **real** data from your locally running MetaTrader 5 terminal into the
cockpit, to validate the full connection path end-to-end with your Exness demo
account. Read `context/realtime/live_prototype.md` for the design and ADR 0007
for why the translation currently runs in the browser.

## Safety (read this)

- **Read-only / `observe` mode.** This script never places, modifies, or closes
  an order. It contains no `order_send` and no trade calls at all.
- **No credentials needed or accepted.** Your terminal is already logged in on
  your machine; `mt5.initialize()` just attaches to it. Never put a password
  anywhere.
- Windows only (the `MetaTrader5` Python package requires it), with the MT5
  terminal **open and logged in**.

## Prerequisites

1. MetaTrader 5 terminal open, logged into your Exness demo account.
2. In the terminal, enable **Tools → Options → Expert Advisors → Allow
   algorithmic trading** is NOT required (we only read), but the symbol must be
   visible in **Market Watch** (right-click → Show All if needed).
3. Python 3.10+.

## Run

```bash
cd tools/mt5-observer
pip install -r requirements.txt
python mt5_observer.py --symbol XAUUSDm
```

You should see:

```
[observer] attached to account 5099xxxx @ Exness Technologies Ltd (Exness-MT5Trial8), balance=1000.0 USD
[observer] READ-ONLY / observe. Serving ws://127.0.0.1:8765
```

Then start the cockpit in live mode. **Most robust (any shell):** create a
`.env.local` at the repo root with:

```ini
NEXT_PUBLIC_REALTIME_SOURCE=live
NEXT_PUBLIC_MT5_WS_URL=ws://localhost:8765
```

then **restart** the dev server (env vars are read at startup):

```powershell
npm run dev
```

Prefer an inline variable instead? Use the right syntax for your shell — and
note the dev server must be (re)started in that same shell:

```powershell
# PowerShell (Windows)
$env:NEXT_PUBLIC_REALTIME_SOURCE="live"; npm run dev
```

```bash
# bash / git-bash
NEXT_PUBLIC_REALTIME_SOURCE=live npm run dev
```

The badge should switch to **DEMO** as soon as the dev server restarts (even
before the producer connects). Set it back to `mock` (or delete `.env.local`)
to return to mock data.

Open http://localhost:3000 — the badge should read **DEMO**, the connection
badge **connected**, and you should see your real balance/equity, real open
positions, live XAUUSD ticks, and a Market Context panel computed by the ICT/SMC
engine from your real M15 candles.

## Options

| Flag | Default | Meaning |
| --- | --- | --- |
| `--symbol` | `XAUUSDm` | Broker symbol (check the exact name in Market Watch) |
| `--host` | `127.0.0.1` | WebSocket host |
| `--port` | `8765` | WebSocket port (match `NEXT_PUBLIC_MT5_WS_URL`) |
| `--candles` | `120` | Number of M15 candles to backfill for the engine |

## Scope / not yet

Account drawdown %, daily P&L baseline, risk gates, signals, and execution are
**not** produced here — those engines don't exist yet, so the cockpit shows
honest empty states for them. This prototype proves the **data path**, nothing
more. The definitive agent is the MQL5 EA + sidecar from the Phase 03 spec.
