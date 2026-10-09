# TradingOsAgent — MT5 execution agent (EA-05)

The execution agent for the Trading Operating System (ADR 0010). It is the **only** component that may ever reach a broker
with an order, and the Python core (`python/trading_os`, ADR 0016) is the only thing it talks to. Reading the market and the
account is the core's own job (`MetaTrader5` in a read-only worker process) — two paths, two responsibilities, never merged.
Read `context/product/tools/EA-05-agent-mql5.md`, `context/execution/{protocol,state-machine,safety}.md` and
`docs/architecture/python-native-architecture.md` (§ 7–8) before touching this code.

## Safety (read this)

- **Exactly one `OrderSend` call exists**, added 2026-09-15 as EA-05 increment 6 on a separate explicit approval (ADR 0010).
  Grep it: one call site, inside `ExecuteOrder`, whose first statement returns unless the mode is `CONFIRM`. No execution path
  reaches a broker without passing that test. `python/tests/architecture/test_execution_agent.py` reads this file and fails if
  that stops being true.
- **Mode is fixed at `OBSERVE`** for the whole lifetime of this build — a compile-time `const`, not an input, not settable by
  any message this agent handles (`control.set_mode` is logged and ignored). So the guard above can never pass and the
  execution body is provably dead code: every accepted command still reports `SIMULATED` today.
- **The path opens increment by increment.** The approvals of 2026-09-25/26 (ADR 0014 arming, EA-07, EA-08, ADR 0015
  autonomy) cover the study's I4 to I8 (`02_Plan_Projet/etude-connexion-pilotage-agent-2026-09-25.md`); each widening lands
  in its own increment, after its ADR or fiche. Not in this build.
- **Local barriers are a last line of defense, never a decision** (ADR 0007). The Risk Engine, in the core, is what decides.
- **Dead-man switch (build 1.11).** A *new* order is refused (`DEAD_MAN`) when the core's `control.ping` has not been heard for
  `InpDeadManSeconds` (30 s by default) — and on a fresh connection until the first ping. See below.

## What this build does

`connect` (with the core's agent token) → `hello` → `heartbeat` / `control.ping` → `receive` → idempotency check → **halt** →
**identity** → account check → expiry check → `validate` (dead-man, then the local barriers) → `acknowledge` → then the mode
fork: `execute` in `CONFIRM` (unreachable here, see Safety) or `report` `SIMULATED` in every other mode — which is every run of
this build. EA-06 reconciliation and position scan run on every connect and heartbeat; final reports of the last hour are sent
again on every connect.

- **Identity comes from the terminal** (`ACCOUNT_LOGIN`, `ACCOUNT_SERVER`), read at start and re-read every second: the
  terminal can switch accounts under a running agent. `InpAccountId` is only an optional expectation: if set and different,
  the agent stays loaded but refuses every command (`IDENTITY_REFUSED`) — never `INIT_FAILED`, which would detach it on each
  account switch. The `accountId` it announces is the login.
- **One instance per terminal.** A second `TradingOsAgent` removes itself (`INIT_FAILED`, with a line in the Experts log).
- **Local halt** and **dead-man switch** — see below.
- **Hello and heartbeat publish** the mode ceiling and effective mode, the build (`1.11`), the capabilities
  (`ping`, `halt`, `dead_man`), `hedging`/`netting`, FIFO, the four trading permissions, the halt, and every other EA attached to
  this terminal (the Algo Trading button arms them all).

On the execution path, the command is written to disk as `UNKNOWN` *before* the broker call and rewritten with the real
outcome after, so an agent that dies mid-call leaves `UNKNOWN` behind and a replay of that `commandId` returns `DUPLICATE`
without ever sending a second order (ADR 0010, "jamais deux positions"). An `UNKNOWN` line that cannot be written stops the
order (`STORE_UNWRITABLE`). The store is one file per login and magic: `MQL5\Files\tradingos_commands_<login>_<magic>.log`.

## Local halt (kill switch)

Works with the core off: its source of truth is a file in `MQL5\Files`.

- **Set it**: the red **HALT Trading OS agent** button on the chart (one click, no dialog), a `control.halt` from the core, or by
  hand: create `MQL5\Files\tradingos_halt.flag` (any content) — halts whatever login the terminal is on.
- **While set**: every new command is refused `HALTED`. It never closes a position (and will never block a close, EA-08).
- **Lift it**: only a human, on the chart — click the button again (it reads **AGENT HALTED - click to lift**) and confirm, or
  delete the flag files (`tradingos_halt.flag`, `tradingos_halt_<login>.flag`). The core can set it, never lift it.

## Dead-man switch

The core sends `control.ping` every 5 s to an agent that announced the `ping` capability. The agent keeps one clock for it,
fed by **nothing else**: a received order is not proof that the core is alive (the clock of "last line seen" moves on every
line, an order included — that one is only telemetry). When no ping has arrived for `InpDeadManSeconds`, or none yet on this
connection, every *new* order is refused with a reason that starts `DEAD_MAN:` — the core reads everything before the first
colon as the code of the refusal. It is a refusal only: it opens nothing, closes nothing, and never touches a stop already
placed at the broker. The limit can be loosened (up to 600 s), never switched off: a value under 5 is read as 30.

An agent built before 1.11 does not have this switch and does not announce the `dead_man` capability — **recompile the file in
MetaEditor and attach the new build** to get it (an EA already attached keeps running the old code until it is removed and
attached again).

## Prerequisites

1. MetaTrader 5 terminal open, logged into the account this agent will serve.
2. The Trading OS core running (`scripts/start.ps1`, or `python -m trading_os serve` from `python/`), listening for this agent
   on `EA_LINK_PORT` (default `9765`, loopback only). This is a **plain TCP** socket carrying one JSON message per line, not
   WebSocket/WSS (`python/trading_os/infrastructure/mt5/ea_link.py` says why).
3. **The agent token** in `MQL5\Files\tradingos_agent.token` — written by `scripts/start.ps1` from `TRADINGOS_AGENT_TOKEN` in
   `.env`. Never an input: an input lands in the preset and the chart properties. Without it the core refuses the agent (it logs
   why).
4. Every symbol in `InpAllowedSymbolsCsv` visible in **Market Watch** (right-click → Show All if needed).
5. The core's address — `127.0.0.1`, the `InpCoreHost` value — added in **Tools → Options → Expert Advisors → Allow WebRequest
   for listed URL**. MT5 checks `SocketConnect` against that list: with the address missing the EA logs `initial connection to
   127.0.0.1:9765 failed (error 4014)` (`ERR_FUNCTION_NOT_ALLOWED`), refused before any network attempt — an allowed address
   with nothing listening gives 5272 instead. The setting is terminal-wide and applies to EAs already running (verified
   2026-09-24).

## Install

1. Copy (or symlink) this folder's `.mq5` and `Include/` into the terminal's `MQL5/Experts/` data folder — MetaEditor's "Open
   Data Folder" button finds it. Preserve the `Include/` subfolder relative to the `.mq5` file.
2. Open `TradingOsAgent.mq5` in MetaEditor and compile (F7). A headless check also works and leaves nothing in the repository
   when run on a copy: `MetaEditor64.exe /compile:"<copy>\TradingOsAgent.mq5" /log:"<copy>\compile.log"` — the last line of the
   log must read `0 errors, 0 warnings` (the exit code of MetaEditor is 1 on success).
3. Attach the compiled EA to **one** chart. `Allow Algo Trading` can stay unchecked while the mode is `OBSERVE` (sockets and
   position reads do not need it), which adds a terminal-side barrier on top of the code's. `InpMagicNumber` must be positive or
   the EA refuses to start (`INIT_PARAMETERS_INCORRECT`).

## Inputs

| Input | Meaning |
| --- | --- |
| `InpCoreHost` / `InpCorePort` | Where the core listens (default `127.0.0.1:9765`). Named `InpGatewayHost` / `InpGatewayPort` before 1.11: a saved preset that still carries the old names is read with the defaults, which are the same values — re-enter them only if you changed them. |
| `InpAccountId` | **Optional.** The login this terminal is expected to be on. Empty = serve whatever login it is on. Set and different = identity `mismatch`: loaded, every command refused. |
| `InpMagicNumber` | **Required, must be unique per environment** (ADR 0010 isolation: one terminal, one agent instance, one magic number per account). Also names the command store. |
| `InpTradableLogins` | CSV of logins on which an order may **ever** reach the broker (CONFIRM only — not in this build). Empty = none. |
| `InpClosableLogins` | CSV of logins on which a close may ever reach the broker (EA-08, I5 — not in this build). Empty = none. |
| `InpHeartbeatSeconds` | Heartbeat interval sent to the core. |
| `InpDeadManSeconds` | Build 1.11. How long the core's ping may stay silent before a new order is refused (`DEAD_MAN`). 5–600, default 30; outside that range it is read as 30. |
| `InpMaxVolumePerOrder` | Local barrier — lots. |
| `InpMaxOpenPositions` | Local barrier — counts **all** positions on this terminal, external ones included (EA-06 fiche decision). |
| `InpMaxSpreadCsv` | Maximum spread **per symbol, in price units**: `EURUSDm=0.00025,XAUUSDm=0.40` (2.5 pips; 40 cents). A symbol with no entry refuses every order (`SPREAD_LIMIT_MISSING`) — no limit is never "unlimited". |
| `InpAllowedSymbolsCsv` | Local whitelist, **broker-side** names (e.g. `XAUUSDm,EURUSDm` — see `context/domain/symbols-broker.md`). Outside it: `SYMBOL_MISMATCH`. |
| `InpMaxSlippagePoints` | `MqlTradeRequest.deviation` on the execution path — a bound on an acceptable fill, never a decision. Unused while the mode is `OBSERVE`. |
| `InpReconciliationLookbackDays` | EA-06: how far back history is searched to resolve an `UNKNOWN`. |
| `InpReportReplayMinutes` | Final reports recorded this recently are sent again on every connect (default 60). |

## Verification procedure

Steps 2 to 4 need a command to reach the agent, which the core sends only on the `CONFIRM` route (the ceiling `TRADING_MODE`
and the autonomy state are the trader's decision; at `OBSERVE` or `PAPER` the core simulates the command itself and sends
nothing). They are run **by the trader** from the cockpit — never by an assistant, never against a live agent. Even then this
build answers `SIMULATED`: no order exists.

1. **Connection and heartbeat.** `GET http://127.0.0.1:8000/api/system/health` — `agentsConnected: 1`; the cockpit's *Agents &
   Audit* page shows the agent with its mode (`OBSERVE`), its build (`1.11`) and its capabilities (`ping`, `halt`, `dead_man`).
   The EA prints only its *first* connection failure — retries (every second) are silent, and so is success — so a quiet
   `Experts` tab proves nothing. About 12 heartbeats per minute at `InpHeartbeatSeconds=5` (twice that means two instances).
   An agent without the token is refused — the core's log says why.
2. **Reception and acknowledgements.** A valid command: `ACCEPTED` then `SIMULATED` come back and appear in the cockpit's
   execution feed.
3. **Local validation.** A symbol outside `InpAllowedSymbolsCsv` (`SYMBOL_MISMATCH`), a volume above `InpMaxVolumePerOrder`
   (`VOLUME_LIMIT`), no stop (`STOP_MISSING`), a symbol without an `InpMaxSpreadCsv` entry (`SPREAD_LIMIT_MISSING`). Identity: set
   `InpAccountId` to another login — the agent stays attached, its hello says `identity: mismatch`, every command comes back
   `IDENTITY_REFUSED`. **Dead-man:** stop the core, restart it, and send a command within the first seconds, before its first
   ping — it comes back `DEAD_MAN`; a command sent once the pings flow is accepted.
4. **Persistence.** Send a command, note its `commandId`. Kill the MT5 terminal process (not just the EA) and restart it. Replay
   the exact same `commandId`. Confirm `DUPLICATE` with the **original** recorded result — never a fresh `SIMULATED`.
5. **Halt.** Stop the core; click **HALT** on the chart; start the core: the heartbeat says `halted: true` and every command
   comes back `HALTED`. Lift it on the chart (button + confirm).
6. **Single instance.** Attach the EA to a second chart: it removes itself, the first keeps running.

## Known limitations of this build

- `agent.hello`'s `symbol` field is singular (a legacy of the single-symbol prototype); this agent may whitelist several
  symbols, but only reports the first one in `hello`. Local barriers still apply to every whitelisted symbol regardless.
- The JSON reader/writer (`Include/JsonLite.mqh`) is a purpose-built flat-object scanner, not a general JSON parser — every
  message this agent **reads** is flat. Do not extend it to a nested payload without rewriting it as a real parser first. (It
  writes arrays — `attachedExperts` — which the core's real JSON parser reads.)
- `PositionsTotal()` counts every position on the terminal, not just this agent's own (EA-06 decision: attribute, never
  loosen).
- An `EXTERNAL_POSITION` line is printed on every heartbeat for each position that is not the agent's — noisy when trading by
  hand alongside.
- The dead-man switch refuses *new* orders; it does not close anything. What protects an open position while the core is gone is
  the stop already placed at the broker.
- The core does not yet require the `dead_man` capability before it allows arming — an agent built before 1.11 can still be
  attached. Recompile it (see above).
