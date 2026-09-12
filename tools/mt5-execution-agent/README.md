# TradingOsAgent — MT5 execution agent (EA-05)

The execution agent for the Trading Operating System (ADR 0010). Distinct
from `tools/mt5-observer/` (read-only market/account telemetry) — two
processes, two responsibilities, never merged. Read
`context/product/tools/EA-05-agent-mql5.md` and
`context/execution/{protocol,state-machine,safety}.md` before touching this
code.

## Safety (read this)

- **No `OrderSend` call exists in this file.** Grep it — there is none. This
  build only ever reports `SIMULATED`, exactly like the read-only Python
  observer's own stub command loop. Adding execution is EA-05 increment 6,
  a separate, explicit approval.
- **Mode is fixed at `OBSERVE`** for the whole lifetime of this build — not
  an input, not settable by any message this agent handles. `control.set_mode`
  is logged and ignored (EA-07's job).
- **Local barriers are a last line of defense, never a decision** (ADR 0007).
  The Risk Engine, upstream, is what actually decides.

## What this build does

`connect` → `heartbeat` → `receive` → idempotency check → account check →
expiry check → `validate` (local barriers) → `acknowledge` → `report`
(always `SIMULATED` for an accepted command). No `reconcile` yet (EA-06);
no `execute` yet (increment 6).

## Prerequisites

1. MetaTrader 5 terminal open, logged into the account this agent will
   serve.
2. The Trading OS Gateway running (`backend/src/TradingOs.Host`), listening
   for this agent on `Cockpit:AgentPort` (default `9765` — see
   `Program.cs`). This is a **plain TCP** socket, not WebSocket/WSS — see
   `Mt5AgentServer.cs`'s doc comment for why.
3. Every symbol in `InpAllowedSymbolsCsv` visible in **Market Watch**
   (right-click → Show All if needed).

## Install

1. Copy (or symlink) this folder's `.mq5` and `Include/` into the
   terminal's `MQL5/Experts/` data folder — MetaEditor's "Open Data Folder"
   button finds it. Preserve the `Include/` subfolder relative to the
   `.mq5` file.
2. Open `TradingOsAgent.mq5` in MetaEditor and compile (F7), or run the
   headless gate (see `context/governance/quality_gates.md`).
3. Attach the compiled EA to any chart. **Every input below is required —
   the EA refuses to start (`INIT_PARAMETERS_INCORRECT`) if `InpAccountId`
   is empty or `InpMagicNumber` is not positive.**

## Inputs

| Input | Meaning |
| --- | --- |
| `InpGatewayHost` / `InpGatewayPort` | Where the Gateway listens (default `127.0.0.1:9765`). |
| `InpAccountId` | **Required.** The Trading OS `accountId` this terminal serves. Must match what the Gateway routes commands to — a mismatch is exactly `ACCOUNT_MISMATCH`, by design. |
| `InpMagicNumber` | **Required, must be unique per environment** (ADR 0010 isolation: one terminal, one agent instance, one magic number per account). Also used to derive the on-disk command-store filename. |
| `InpHeartbeatSeconds` | Heartbeat interval sent to the Gateway. |
| `InpMaxVolumePerOrder` | Local barrier — lots. |
| `InpMaxOpenPositions` | Local barrier — counts **all** positions on this terminal; excluding externally-opened ones is EA-06. |
| `InpMaxSpreadPoints` | Local barrier — re-checked at validation time, not just when a setup was proposed. |
| `InpAllowedSymbolsCsv` | Local whitelist, **broker-side** names (e.g. `EURUSDm,GBPUSDm` — see `context/domain/symbols-broker.md`). |

## Verification procedure (do this before moving to the next increment)

Each step below corresponds to one increment in
`context/product/tools/EA-05-agent-mql5.md`. Do not skip ahead.

1. **Connexion et heartbeat.** Start the Gateway, attach the EA. Check
   `GET http://localhost:5080/health` — `agentConnected` should turn `true`,
   and the Gateway log should show `MT5 execution agent connected`. The
   EA's own `Journal`/`Experts` tab in MetaTrader should show no connection
   errors after the first retry.
2. **Réception et accusés.** Send a test `execution.order` through the
   cockpit's command path (same shape `CockpitHub.SubmitCommand` already
   uses for the Python observer). Confirm `execution.ack` (`ACCEPTED`) then
   `execution.report` (`SIMULATED`) arrive and are visible in the cockpit —
   this is the same command loop already validated live against the Python
   observer stub, now carried by this agent instead.
3. **Validation locale.** Send a command with a symbol NOT in
   `InpAllowedSymbolsCsv`, a volume above `InpMaxVolumePerOrder`, no
   stop-loss, and — most importantly — an `accountId` that does not match
   `InpAccountId`. Confirm each is `REJECTED` with the right reason, and
   that `ACCOUNT_MISMATCH` is tested against a **real** second account, not
   simulated.
4. **Persistance.** Send a command, note its `commandId`. Kill the MT5
   terminal process (not just the EA) and restart it. Replay the exact same
   `commandId`. Confirm the response is `DUPLICATE` with the **original**
   recorded result — never a fresh `SIMULATED`.

Only once all four are confirmed does increment 6 (execution) get written —
and only with explicit approval, separately, per the fiche.

## Known limitations of this build

- `agent.hello`'s `symbol` field is singular (a legacy of the single-symbol
  observer prototype); this agent may whitelist several symbols, but only
  reports the first one in `hello`. Local barriers still apply to every
  whitelisted symbol regardless.
- The JSON reader/writer (`Include/JsonLite.mqh`) is a purpose-built
  flat-object scanner, not a general JSON parser — every message this agent
  handles today is flat (no nested objects/arrays). Do not extend it to a
  nested payload without rewriting it as a real parser first.
- `PositionsTotal()` counts every position on the terminal, not just this
  agent's own (magic-number filtering for external positions is EA-06).
