# TradingOsAgent — MT5 execution agent (EA-05)

The execution agent for the Trading Operating System (ADR 0010). Distinct
from `tools/mt5-observer/` (read-only market/account telemetry) — two
processes, two responsibilities, never merged. Read
`context/product/tools/EA-05-agent-mql5.md` and
`context/execution/{protocol,state-machine,safety}.md` before touching this
code.

## Safety (read this)

- **Exactly one `OrderSend` call exists**, added 2026-09-15 as EA-05
  increment 6 on a separate explicit approval (ADR 0010). Grep it: one call
  site, inside `ExecuteOrder`, whose first statement returns unless the mode
  is `CONFIRM`. No execution path reaches a broker without passing that test.
- **Mode is fixed at `OBSERVE`** for the whole lifetime of this build — a
  compile-time `const`, not an input, not settable by any message this agent
  handles (`control.set_mode` is logged and ignored). So the guard above can
  never pass and the execution body is provably dead code: every accepted
  command still reports `SIMULATED` today.
- **The path opens increment by increment.** The approvals of 2026-09-25/26
  (ADR 0014 arming, EA-07, EA-08, ADR 0015 autonomy) cover the study's I4 to
  I8 (`02_Plan_Projet/etude-connexion-pilotage-agent-2026-09-25.md`); each
  widening lands in its own increment, after its ADR or fiche. Not in this
  build.
- **Local barriers are a last line of defense, never a decision** (ADR 0007).
  The Risk Engine, upstream, is what actually decides.

## What this build does (I1, 2026-09-26)

`connect` (with the Gateway token) → `hello` → `heartbeat` / `control.ping`
→ `receive` → idempotency check → **halt** → **identity** → account check
→ expiry check → `validate` (local barriers) → `acknowledge` → then the
mode fork: `execute` in `CONFIRM` (unreachable here, see Safety) or `report`
`SIMULATED` in every other mode — which is every run of this build. EA-06
reconciliation and position scan run on every connect and heartbeat; final
reports of the last hour are sent again on every connect.

- **Identity comes from the terminal** (`ACCOUNT_LOGIN`, `ACCOUNT_SERVER`),
  read at start and re-read every second: the terminal can switch accounts
  under a running agent. `InpAccountId` is only an optional expectation: if
  set and different, the agent stays loaded but refuses every command
  (`IDENTITY_REFUSED`) — never `INIT_FAILED`, which would detach it on each
  account switch. The `accountId` it announces is the login.
- **One instance per terminal.** A second `TradingOsAgent` removes itself
  (`INIT_FAILED`, with a line in the Experts log).
- **Local halt** — see below.
- **Hello and heartbeat publish** the mode ceiling and effective mode, the
  build, `hedging`/`netting`, FIFO, the four trading permissions, the halt,
  and every other EA attached to this terminal (the Algo Trading button arms
  them all).

On the execution path, the command is written to disk as `UNKNOWN` *before*
the broker call and rewritten with the real outcome after, so an agent that
dies mid-call leaves `UNKNOWN` behind and a replay of that `commandId`
returns `DUPLICATE` without ever sending a second order (ADR 0010, "jamais
deux positions"). Since I1, an `UNKNOWN` line that cannot be written stops
the order (`STORE_UNWRITABLE`). The store is one file per login and magic:
`MQL5\Files\tradingos_commands_<login>_<magic>.log`.

## Local halt (kill switch)

Works with the backend off: its source of truth is a file in `MQL5\Files`.

- **Set it**: the red **HALT Trading OS agent** button on the chart (one
  click, no dialog), a `control.halt` from the Gateway, or by hand: create
  `MQL5\Files\tradingos_halt.flag` (any content) — halts whatever login the
  terminal is on.
- **While set**: every new command is refused `HALTED`. It never closes a
  position (and will never block a close, EA-08).
- **Lift it**: only a human, on the chart — click the button again (it reads
  **AGENT HALTED - click to lift**) and confirm, or delete the flag files
  (`tradingos_halt.flag`, `tradingos_halt_<login>.flag`). The Gateway can set
  it, never lift it.

## Prerequisites

1. MetaTrader 5 terminal open, logged into the account this agent will
   serve.
2. The Trading OS Gateway running (`backend/src/TradingOs.Host`), listening
   for this agent on `Cockpit:AgentPort` (default `9765` — see
   `Program.cs`). This is a **plain TCP** socket, not WebSocket/WSS — see
   `Mt5AgentServer.cs`'s doc comment for why.
3. **The Gateway token** in `MQL5\Files\tradingos_agent.token` — written by
   `scripts/start-live.ps1` from `TRADINGOS_AGENT_TOKEN` in `.env` (I1).
   Never an input: an input lands in the preset and the chart properties.
   Without it the Gateway refuses the agent (it logs why, once a minute).
4. Every symbol in `InpAllowedSymbolsCsv` visible in **Market Watch**
   (right-click → Show All if needed).
5. The Gateway address — `127.0.0.1`, the `InpGatewayHost` value — added in
   **Tools → Options → Expert Advisors → Allow WebRequest for listed URL**.
   MT5 checks `SocketConnect` against that list: with the address missing
   the EA logs `initial connection to 127.0.0.1:9765 failed (error 4014)`
   (`ERR_FUNCTION_NOT_ALLOWED`), refused before any network attempt — an
   allowed address with nothing listening gives 5272 instead. The setting
   is terminal-wide and applies to EAs already running (verified
   2026-09-24).

## Install

1. Copy (or symlink) this folder's `.mq5` and `Include/` into the
   terminal's `MQL5/Experts/` data folder — MetaEditor's "Open Data Folder"
   button finds it. Preserve the `Include/` subfolder relative to the
   `.mq5` file. (On this machine: a junction, see the runbook.)
2. Open `TradingOsAgent.mq5` in MetaEditor and compile (F7), or run the
   headless gate (see `context/governance/quality_gates.md`). After a
   headless compile, an EA already attached keeps running the old code
   until it is removed and attached again (verified 2026-09-24).
3. Attach the compiled EA to **one** chart. `Allow Algo Trading` can stay
   unchecked while the mode is `OBSERVE` (sockets and position reads do not
   need it), which adds a terminal-side barrier on top of the code's.
   `InpMagicNumber` must be positive or the EA refuses to start
   (`INIT_PARAMETERS_INCORRECT`).

## Inputs

| Input | Meaning |
| --- | --- |
| `InpGatewayHost` / `InpGatewayPort` | Where the Gateway listens (default `127.0.0.1:9765`). |
| `InpAccountId` | **Optional since I1.** The login this terminal is expected to be on. Empty = serve whatever login it is on. Set and different = identity `mismatch`: loaded, every command refused. |
| `InpMagicNumber` | **Required, must be unique per environment** (ADR 0010 isolation: one terminal, one agent instance, one magic number per account). Also names the command store. |
| `InpTradableLogins` | I1. CSV of logins on which an order may **ever** reach the broker (CONFIRM only — not in this build). Empty = none. |
| `InpClosableLogins` | I1. CSV of logins on which a close may ever reach the broker (EA-08, I5 — not in this build). Empty = none. |
| `InpHeartbeatSeconds` | Heartbeat interval sent to the Gateway. |
| `InpMaxVolumePerOrder` | Local barrier — lots. |
| `InpMaxOpenPositions` | Local barrier — counts **all** positions on this terminal, external ones included (EA-06 fiche decision). |
| `InpMaxSpreadCsv` | I1, replaces `InpMaxSpreadPoints`. Maximum spread **per symbol, in price units**: `EURUSDm=0.00025,XAUUSDm=0.40` (2.5 pips; 40 cents). A symbol with no entry refuses every order (`SPREAD_LIMIT_MISSING`) — no limit is never "unlimited". A single point limit of 50 refused every XAUUSDm order (≈ 260 points at 3 digits). |
| `InpAllowedSymbolsCsv` | Local whitelist, **broker-side** names (e.g. `XAUUSDm,EURUSDm` — see `context/domain/symbols-broker.md`). Outside it: `SYMBOL_MISMATCH`. |
| `InpMaxSlippagePoints` | `MqlTradeRequest.deviation` on the execution path — a bound on an acceptable fill, never a decision. Unused while the mode is `OBSERVE`. |
| `InpReconciliationLookbackDays` | EA-06: how far back history is searched to resolve an `UNKNOWN`. |
| `InpReportReplayMinutes` | I1: final reports recorded this recently are sent again on every connect (default 60). |

## Verification procedure

Each step corresponds to an increment in
`context/product/tools/EA-05-agent-mql5.md`. Commands are sent with the dev
harness — **run by the trader**, never by Claude against a live agent:

```bash
npx tsx scripts/dev-submit-command.ts --account <login> --symbol EURUSDm --side buy --volume 0.01 --sl <price> --tp <price>
```

1. **Connexion et heartbeat.** `GET http://localhost:5080/health` —
   `agentConnected: true`; the Gateway log shows `MT5 execution agent
   connected`. The EA prints only its *first* connection failure — retries
   (every second) are silent, and so is success — so a quiet `Experts` tab
   proves nothing. The database holds one `agent.connected` envelope for
   `mt5-execution-agent-<magic>` and ~12 `agent.heartbeat` per minute at
   `InpHeartbeatSeconds=5` (twice that means two instances). Passed for the
   first time on 2026-09-24 (Exness demo, `EURUSDm`). Since I1: an agent
   without the token is refused — `docker logs tradingos-backend` says why.
2. **Réception et accusés.** A valid command through the harness: `ACCEPTED`
   then `SIMULATED` come back, and appear in the cockpit's execution feed.
3. **Validation locale.** Through the harness: a symbol outside
   `InpAllowedSymbolsCsv` (`SYMBOL_MISMATCH`), a volume above
   `InpMaxVolumePerOrder` (`VOLUME_LIMIT`), `--sl 0` (`STOP_MISSING`), a
   symbol without `InpMaxSpreadCsv` entry (`SPREAD_LIMIT_MISSING`). Identity:
   set `InpAccountId` to another login — the agent stays attached, its hello
   says `identity: mismatch`, every command comes back `IDENTITY_REFUSED`.
   (A real `ACCOUNT_MISMATCH` needs the Gateway to misroute a command: since
   I1 the agent registers under its real login, so it is defence in depth.)
4. **Persistance.** Send a command, note its `commandId`. Kill the MT5
   terminal process (not just the EA) and restart it. Replay the exact same
   `commandId`. Confirm `DUPLICATE` with the **original** recorded result —
   never a fresh `SIMULATED`.
5. **Halt (I1).** Stop the backend; click **HALT** on the chart; start the
   backend: the heartbeat says `halted: true` and every command comes back
   `HALTED`. Lift it on the chart (button + confirm).
6. **Instance unique (I1).** Attach the EA to a second chart: it removes
   itself, the first keeps running.

## Known limitations of this build

- `agent.hello`'s `symbol` field is singular (a legacy of the single-symbol
  observer prototype); this agent may whitelist several symbols, but only
  reports the first one in `hello`. Local barriers still apply to every
  whitelisted symbol regardless.
- The JSON reader/writer (`Include/JsonLite.mqh`) is a purpose-built
  flat-object scanner, not a general JSON parser — every message this agent
  **reads** is flat. Do not extend it to a nested payload without rewriting
  it as a real parser first. (It writes arrays — `attachedExperts` — which
  the Gateway's real JSON parser reads.)
- `PositionsTotal()` counts every position on the terminal, not just this
  agent's own (EA-06 decision: attribute, never loosen).
- An `EXTERNAL_POSITION` line is printed on every heartbeat for each
  position that is not the agent's — noisy when trading by hand alongside.
- `control.ping` only feeds `gatewaySilentMs` for now; a silent Gateway
  disarms the agent once arming exists (ADR 0014, I4).
