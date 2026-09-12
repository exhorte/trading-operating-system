# MT5 Wire Protocol (Lean Edge)

The MT5 agent and the WebSocket Gateway exchange **secure WebSocket (WSS) messages** in a lean, versioned JSON format. This protocol is intentionally simpler than the internal `Envelope<T>` — the gateway is the adapter between the two. Canonical types: `lib/contracts/mt5-wire.ts`. Session lifecycle: `context/realtime/mt5_agent_realtime_lifecycle.md`.

## Why Two Protocols

| Concern | MT5 edge (this doc) | Internal (Envelope<T>) |
| --- | --- | --- |
| Client | MQL5 EA via sidecar | .NET services, dashboard |
| Transport | raw WSS | SignalR / in-process |
| Envelope | flat, `version`, `time` epoch, `id` | `messageId`/`correlationId`/`causationId`, `schemaVersion`, ISO `sentAt`, nested `payload` |
| Side | `"BUY"` / `"SELL"` | `"buy"` / `"sell"` |
| Reason | MQL5 has no SignalR client; keep the EA trivial (`Connect/Send/Receive/Reconnect`) | full audit/correlation for decision replay |

MQL5 has no maintained SignalR client, so forcing SignalR onto the EA would mean hand-rolling negotiation, framing, and reconnection. Raw WSS + lean JSON keeps the agent simple; the gateway adds the correlation and audit metadata the platform needs.

## Common Envelope

Every message carries:

| Field | Type | Notes |
| --- | --- | --- |
| `version` | number | lean protocol version (currently `1`) |
| `type` | string | message type (see families below) |
| `accountId` | string | platform account this agent serves |
| `time` | number | Unix epoch **milliseconds**, UTC |

> The user's original sketch used `time` in epoch seconds (`1780000000`). This spec uses milliseconds so two ticks in the same second stay ordered; the gateway converts to ISO `UtcTimestamp`.

## Message Families

Agent → Gateway (telemetry & lifecycle):

- `agent.hello` — capabilities on connect/reconnect (symbol, broker, order types, volume min/max/step, filling mode, stops level, boot mode)
- `agent.heartbeat`
- `agent.error`
- `market.tick`
- `market.candle`
- `account.snapshot`
- `positions.snapshot`
- `execution.ack` — immediate receipt, echoes command `id`
- `execution.report` — terminal outcome, echoes command `id`

Gateway → Agent (control & commands):

- `execution.order`
- `execution.modify`
- `execution.close`
- `execution.close_all`
- `execution.cancel`
- `control.set_mode`
- `control.resync`

## Examples

Tick (agent → gateway):

```json
{ "version": 1, "type": "market.tick", "accountId": "ftmo-001", "symbol": "XAUUSD", "bid": 3352.45, "ask": 3352.62, "time": 1780000000000 }
```

Order command (gateway → agent):

```json
{ "version": 1, "type": "execution.order", "accountId": "ftmo-001", "id": "cmd-1245", "symbol": "XAUUSD", "side": "BUY", "orderType": "MARKET", "volume": 0.20, "limitPrice": null, "sl": 3348.50, "tp": 3364.00, "expiresAt": 1780000005000, "time": 1780000000000 }
```

Ack then report in `observe` mode (agent → gateway):

```json
{ "version": 1, "type": "execution.ack", "accountId": "ftmo-001", "commandId": "cmd-1245", "status": "ACCEPTED", "reason": null, "time": 1780000000100 }
```
```json
{ "version": 1, "type": "execution.report", "accountId": "ftmo-001", "commandId": "cmd-1245", "status": "SIMULATED", "symbol": "XAUUSD", "side": "BUY", "brokerOrderId": null, "brokerPositionId": null, "filledVolume": null, "averagePrice": null, "brokerRetcode": null, "detail": "observe mode: order not sent to broker", "time": 1780000000150 }
```

## Execution Modes

The agent applies a mode to every command; the command payload is identical across modes.

| Mode | Terminal action | Report status |
| --- | --- | --- |
| `observe` (default) | never sends to broker | `SIMULATED` |
| `paper` | routes to a demo account | real broker statuses |
| `confirm` | routes to the real broker, one order at a time, only after explicit human validation (EA-07) | real broker statuses |

> Renamed from `live` (EA-05) to match ADR 0010's ladder — `confirm` names
> the actual safety property of this rung (per-order human approval), not
> just "is this a real-money account".

Agent config:

```yaml
execution:
  enabled: false   # false ⇒ observe regardless of mode
  mode: observe    # observe → paper → confirm
```

Backend counterpart: the Trading Engine talks to an `ExecutionAdapter` (`NullExecution` / `PaperExecution` / `MT5Execution` / future `FIXExecution`) and never knows which is active. `LocalRiskGuard` treats an unknown or absent mode as `observe` — the safe default.

## Gateway Translation

Inbound (MT5 lean → internal `Envelope<T>` + domain, see `lib/contracts` / `lib/domain`):

| MT5 field | Internal | Transform |
| --- | --- | --- |
| — | `messageId` | gateway generates a UUID |
| — | `correlationId` / `causationId` | assigned per workflow (signal→command→report) |
| `version` | `schemaVersion` | copied |
| `type` | `type` (EventType) | mapped (`market.tick` → `market.tick`, `execution.report` → `execution.*` family) |
| `time` | `sentAt` | epoch ms → ISO `UtcTimestamp` |
| `accountId` | `source` | `"mt5-agent:{accountId}"` |
| `side` `"BUY"` | domain `Side` `"buy"` | lowercased |
| flat fields | `payload` (domain model) | reshaped into `MarketTickPayload`, `ExecutionReport`, … |

Outbound (internal `ExecutionCommand` → MT5 lean):

| Internal | MT5 field | Transform |
| --- | --- | --- |
| `commandId` | `id` | copied |
| `kind` `"place_order"` | `type` `"execution.order"` | mapped |
| `side` `"buy"` | `side` `"BUY"` | uppercased |
| `stopLoss` / `takeProfit` | `sl` / `tp` | renamed |
| `expiresAt` (ISO) | `expiresAt` (number) | ISO → epoch ms |
| correlation/envelope metadata | — | dropped at the edge |

## Idempotency, Retry, Reconciliation

- The agent dedupes commands by `id`; a repeat `id` gets `execution.ack` with status `DUPLICATE` and no re-execution.
- The agent refuses any command past its `expiresAt` with status `EXPIRED`.
- Every `execution.ack` and `execution.report` echoes the originating command `id`; the gateway/engine reconcile reports against intended commands.
- On reconnect the agent re-sends `agent.hello`, then `account.snapshot` and `positions.snapshot`; the engine reconciles open positions and pending commands before execution is re-enabled. No new command is trusted until reconciliation completes.
