# ADR 0010 - Execution Bridge In Observe/SIMULATED Mode

## Status

Accepted

## Context

Phases 04–08 built the engines, the Signal → RiskDecision flow, and the .NET gateway. The user chose to validate the full execution command loop next — at zero risk, before any persistence or paper trading. Their absolute constraints: observe mode only, no MT5 order call of any kind, no implicit broker fallback, absent/unknown mode = refuse, volume strictly from the approved `RiskDecision`, rejected/expired commands never produce a fill, business logic out of the UI, C# contracts 1:1 with TypeScript.

## Decision

Ship the command loop end-to-end with SIMULATED outcomes:

1. **Origin (transitional, in-browser):** the strategy stub + risk review run in `SignalRRealtimeClient` on REAL context/risk (the engines already live there). `buildPlaceOrderCommand` (`lib/execution/command-builder.ts`, pure, tested) is the only way a command exists: approved + sized decision only, `volume = approvedVolume`, `riskApprovalId` linked, rejected/unsized/mismatched → `null`.
2. **Hub:** `CockpitHub.SubmitCommand` broadcasts the command envelope to every dashboard (single source of truth), then guards: agent `hello.mode != "observe"` (absent/unknown included) → synthesized `rejected` ack, never forwarded. Otherwise `Mt5WireTranslator.FlattenPlaceOrder` (id=commandId, ISO→epoch expiry, uppercase side/type, ADR 0005 tables) and one outbound frame to the agent.
3. **Agent (observer):** new consumer loop. Strict validation (required fields, MARKET only, served symbol, volume > 0 and within broker min/max, **mandatory stop**), expiry check, dedup by command id (`DUPLICATE` ack), constant `EXECUTION_MODE = "observe"`. Valid → `execution.ack ACCEPTED` then `execution.report SIMULATED` (current tick as price). **No trade function is imported anywhere — a "fill" is a JSON reply.** Rejected/expired/duplicate → ack only, never a report.
4. **Up-path:** gateway translates ack → `execution.command.acknowledged`/`.rejected` with the canonical `CommandAckPayload` (resolving the Phase 01/02 shortcut) and SIMULATED reports → the new `execution.order.simulated` event. New domain status `"simulated"` (TS + C#), rendered with its own tone — **never as a fill**.
5. **Client lifecycle:** store tracks `commands` (sent → retried/acknowledged/rejected/expired/failed/reported) and drives signal statuses. Ack timeout 5 s → **one** idempotent retry with the same commandId (a `DUPLICATE` ack counts as confirmation) → `failed`. No implicit resend on reconnect.

## Consequences

- Idempotency, expiry, validation, ack/report plumbing, and the risk-approval gate are now exercised for real, end-to-end, at zero risk — the exact groundwork paper/live execution will reuse with a different terminal action.
- Safety is layered: risk-gated builder → hub mode guard → agent mode constant + no trade imports → distinct `simulated` status. Four independent barriers before any future broker call.
- The in-browser decision loop remains transitional debt (documented here and in ADR 0009); porting engines server-side is a later phase.
- Only `place_order` is bridged; modify/close/cancel and `control.set_mode` are deferred.
- Nothing persists: command/decision/ack/report audit is in-memory + cockpit feed. **Persistence (PostgreSQL/Timescale) is the next phase, before any paper trading** (user decision).
