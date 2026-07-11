# Phase 09 - Execution Bridge (observe/SIMULATED)

Status: closed 2026-07-11 (implemented the same day per the user's 10-point spec, committed `57e96b1`; design validated first). **Validated live by the user**: signals (both sides, counter-bias sell included) → risk-sized decisions with varied volumes (0.12–0.28 lot tracking stop distance) → commands → ACCEPTED acks → `simulated` reports ("observe mode, no broker order") in the cockpit feed. The run also exercised **real idempotency**: a cockpit restart without restarting the observer replayed counter-based ids → the agent's persistent dedup set answered DUPLICATE and refused to re-simulate (no double fill) — exactly as specified. Two fixes folded in at closure: session-unique signal/command ids (`sig-{runId}-{seq}`, collisions across restarts/tabs eliminated) and confirmations no longer overwrite the risk-decision text on signal cards.

## Objective

Validate the full execution command loop at zero risk: approved `RiskDecision` → `PlaceOrderCommand` → hub → .NET gateway flatten (ADR 0005) → observer validation/dedup → `execution.ack` → `execution.report SIMULATED` → back up to the cockpit with full signal/command lifecycle. No broker order can exist anywhere on this path.

## Spec coverage (user's 10 points)

- **(1)** Command only from an approved decision — `buildPlaceOrderCommand` returns null otherwise (tested).
- **(2)** Gateway flatten to lean `execution.order` — `FlattenPlaceOrder` (xUnit).
- **(3–4)** Observer receives + validates id/expiry/mode/required fields/volume bounds/mandatory SL.
- **(5)** Dedup by commandId → `DUPLICATE` ack, no report.
- **(6–7)** `execution.ack` then `execution.report SIMULATED`.
- **(8)** Gateway → SignalR → cockpit (`execution.command.acknowledged|rejected` = canonical `CommandAckPayload`; `execution.order.simulated`).
- **(9)** Store: `commands` map (sent→retried/acknowledged/rejected/expired/failed/reported) + signal statuses commanded→acknowledged→reported (tested).
- **(10)** Errors/timeouts/duplicates/expiry/reconnects: 5s ack timeout → one same-id retry (DUPLICATE = confirmation) → failed; rejected/expired never fill (tested); no implicit resend on reconnect.

## Constraints honored

Observe only; no MT5 order call (grep-clean: no trade function imported); no demo/live order; no implicit broker fallback; absent/unknown mode refused (hub guard + agent constant); volume = `approvedVolume`; rejected/expired never fill; business logic in `lib/` (not UI); C# mirrors 1:1 (14/14 xUnit mirroring TS semantics); design validated before code.

## Implementation Notes (2026-07-11)

TS: domain `ExecutionReportStatus` += `"simulated"`; EventType += `execution.order.simulated`; ack events now carry canonical `CommandAckPayload` (Phase 01/02 shortcut resolved). `lib/execution/command-builder.ts` (+3 tests). Store: `ExecutionCommandView` read model, `commands` map, lifecycle cases, `markCommandRetried/Failed` (+6 tests). `SignalRRealtimeClient`: transitional decision loop (30 s cadence on real context/risk), `SubmitCommand` invoke, 5 s timeout + single retry. Feed pill `simulated` = accent tone (never profit).

C#: `Execution.cs` mirrors (`PlaceOrderCommand`, `CommandAck`, `ExecutionReportView`, lean `Mt5OrderCommand/Mt5AckMessage/Mt5ReportMessage`), parser cases, `FlattenPlaceOrder`/`ToCommandAck`/`ToExecutionReport`, `Mt5ObserverClient.SendCommandAsync` (first outbound frame), `CockpitHub.SubmitCommand` + observe-mode guard + synthesized rejection. 14/14 xUnit.

Python observer v0.2.0: producer‖consumer (`asyncio.TaskGroup`), strict validation, module-level dedup set (survives reconnects), `EXECUTION_MODE = "observe"` constant, SIMULATED report with live tick price. Still zero trade calls.

Gates: lint clean, source `tsc` exit 0, 56 Vitest (9 new), dotnet build 0/0 + 14/14, `py_compile` OK.

## Next

Persistence (PostgreSQL/Timescale) for commands/decisions/acks/reports/candles/audit — **before any paper trading** (user decision).
