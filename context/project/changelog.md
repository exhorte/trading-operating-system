# Changelog

This file tracks meaningful changes to the project brain and architecture.

## 2026-07-06

### Added - AI Project Brain

- Created `.claude/` operating instructions for Claude Code.
- Created the `context/` project brain.
- Added project manifesto, roadmap, phase files, memory, and handoff.
- Added architecture overview and bounded contexts.
- Added trading ontology, ICT/SMC framework notes, FTMO risk context, and EA analysis.
- Added engineering stack, standards, testing strategy, governance, workflows, prompts, ADRs, and agent role definitions.

### Added - Source Analysis

- Indexed source notes from `../NOTES/`.
- Analyzed `Ultimate_ICT_Gold_Scalper_v4.0.mq5`.
- Documented that the EA is a knowledge source and future MT5 execution/telemetry agent, not the platform brain.

### Changed - WebSocket-First Architecture

- Replaced API-first direction with WebSocket/SignalR-first architecture for trading flows.
- Added `context/realtime/`.
- Added realtime event envelope, event families, execution commands, acknowledgements, and execution report examples.
- Added MT5 agent realtime lifecycle guidance.
- Updated architecture, backend plan, frontend plan, stack, governance, prompts, roadmap, phases, and handoff.

### Added - ADR

- Added `ADR 0001 - Platform Over EA`.
- Added `ADR 0002 - Next.js Dashboard And .NET Backend Target`.
- Added `ADR 0003 - WebSocket-First Infrastructure`.

### Added - Visual Interface Direction

- Analyzed visual references added in `context/templates/`.
- Added `context/templates/README.md`.
- Added `context/frontend/visual_reference_analysis.md`.
- Added `context/frontend/final_interface_spec.md`.
- Updated Phase 01 to use the visual spec.

### Changed - Phase 00 Closure

- Audited Phase 00 against its acceptance criteria; all met.
- Committed the full project brain (`.claude/`, `context/`, `CLAUDE.md`) to git for durability.
- Renamed visual reference images in `context/templates/` to descriptive `reference-*` names and updated `frontend/visual_reference_analysis.md`.
- Closed Phase 00; Phase 01 - Frontend Foundation is now the active phase.

### Added - Phase 01 Frontend Foundation

- Added the Phase 01 technical design (`project/phases/phase-01-design.md`), validated by the user.
- Implemented the cockpit shell (icon rail, sidebar, top command bar with MOCK and WebSocket badges).
- Implemented the Command Center with 8 realtime panels and 9 stub screens with empty states.
- Added `lib/contracts/` (envelope, events, read models), `lib/realtime/` (client seam, store, mock client, provider), `lib/mock/` (enveloped generators), and the dark cockpit theme.
- Zero new runtime dependencies; lint and build pass with 11 routes.
- Removed create-next-app boilerplate (homepage, public SVGs).

## 2026-07-07

### Added - Phase 02 Domain Model MVP

- Added the Phase 02 technical design (`project/phases/phase-02-design.md`); implemented in direct continuation at the user's request.
- Added `lib/domain/` as the canonical portable schema source: primitives, market, account, analysis (ICT/SMC), risk, strategy, execution modules.
- Extended `lib/contracts/` into the wire layer: new `commands.ts` (execution commands, CommandAck, RealtimeSubscription), full event payload coverage with `EventPayloadMap` and `KnownEnvelope<T>`, `enums.ts` re-exporting domain vocabulary (`RiskState` kept as alias of `RiskMode`).
- Added `context/domain/domain_model_mvp.md` (layering, portability rules, .NET/MQL5 mapping conventions, traceability chain).
- Added `ADR 0004 - TypeScript Domain Schemas As Canonical Source (MVP)`.
- No UI changes, no new dependencies; lint, typecheck, and build pass.

### Added - Phase 03 MT5 Agent Specification

- Added the Phase 03 technical design (`project/phases/phase-03-design.md`) capturing three user decisions: lean WSS+JSON MT5 edge with a translating WebSocket Gateway (SignalR dashboard-side only), full command loop gated by `observe`/`paper`/`live` execution modes, and an external sidecar bridge for MQL5 networking.
- Added `context/realtime/mt5_wire_protocol.md` (lean edge protocol, examples, execution modes, gateway translation tables).
- Added `lib/contracts/mt5-wire.ts` (canonical lean-edge TS types mirrored by the EA and gateway).
- Extended `context/realtime/mt5_agent_realtime_lifecycle.md` with the sidecar topology and execution modes.
- Added `ADR 0005 - MT5 Lean WebSocket Wire, Gateway Translation, Sidecar, Execution Modes`.
- Documentation + wire contracts only; no EA/sidecar/gateway code. Lint and typecheck pass.

## 2026-07-10

### Added - Mock Variety (rotating scenarios + varied signals)

- `mockRiskContext(scenario)`: rotating conditions normal / wide_spread (55 pts > 40 limit) / closed_session (NY PM disabled); the mock client publishes the same state to the Risk panel that the signal review uses, so rejections always match the cockpit.
- `mockStrategySignal`: every 4th signal is a counter-bias probe (`ict-liquidity-raid-v1`, weaker score); stop distance cycles 3.5–8.0 so volumes vary. Sanity over one rotation: sell 2.89 lot, buy 2.02, spread-gate rejection, buy 1.26, session-filter rejection.

### Changed - Phases 06 + 07 Closed

- Closed Phase 06 (Risk & Prop Firm Mode) and Phase 07 (Signal → Risk Review + `/signals` workspace + mock variety) after the user reviewed both in the running cockpit (risk panel live on the real demo; `/signals` audit view showing real decisions, gates, and fills).
- Updated phase files (closure sections), `project_state.md`, `roadmap.md` (Phase 08 = ASP.NET Core Backend Bootstrap; Execution Bridge → 09, Backtesting → 10), this changelog, `handoff.md`.

### Added - Phase 08 ASP.NET Core Backend Bootstrap

- Added the Phase 08 design (`project/phases/phase-08-design.md`), validated by the user (backend in this repo under `backend/`; minimal observe-only stateless slice), then implemented the same day.
- Added `backend/TradingOs.slnx` (.NET 10): `TradingOs.Contracts` (C# mirrors: `Envelope<T>`, lean mt5-wire records + `Mt5WireParser`, camelCase read models), `TradingOs.Gateway` (`Mt5WireTranslator` — C# port of `mt5-translate.ts`; `GatewayState`; `Mt5ObserverClient` WS client dialing the Python observer, read-only, auto-reconnect), `TradingOs.Host` (SignalR `CockpitHub` `/hub/cockpit` with `GetSnapshot` + `event` envelope broadcasts, `/health`, dev CORS, `GatewayBridgeService`), 7 xUnit tests mirroring the TS translator tests.
- Frontend: `lib/realtime/signalr-client.ts` (`SignalRRealtimeClient` behind the seam; snapshot hydrate + event stream; TS engines on relayed candles + observe-mode risk), provider source `backend`, store `agent.snapshot.positions` case, `@microsoft/signalr` (first runtime dependency), `.env.example`/`.gitignore` updates.
- Added ADR 0009 and `context/backend/backend_bootstrap.md` (3-terminal runbook). Resolves the mono-repo open question (single repo).
- Verified: `dotnet build` 0 warnings/0 errors, `dotnet test` 7/7, host smoke test (`/health` 200, SignalR negotiate 200), frontend lint clean / source `tsc` exit 0 / 47 Vitest tests.

## 2026-07-11

### Changed - Phase 08 Closed; LiveRealtimeClient Deleted

- Closed Phase 08 after the user's live 3-terminal validation (`/health` OK; cockpit DEMO + connected on the real demo with server-side translation).
- Deleted the superseded `lib/realtime/live-client.ts` (ADR 0007 browser shortcut); provider now offers `mock` (default) and `backend` only; `.env.example` simplified; `mt5-translate.ts` + tests kept as the TS reference the C# port mirrors 1:1.

### Added - Phase 09 Execution Bridge (observe/SIMULATED)

- Implemented the user's 10-point spec (design validated first): approved `RiskDecision` → `buildPlaceOrderCommand` (`lib/execution/`, volume = approvedVolume, null when rejected/unsized) → `CockpitHub.SubmitCommand` (observe-mode guard, synthesized rejection otherwise) → lean `execution.order` flatten (ADR 0005) → observer validation (fields/expiry/volume bounds/mandatory SL) + dedup by commandId → `execution.ack` + `execution.report SIMULATED` → canonical `CommandAckPayload` + new `execution.order.simulated` event → store lifecycle.
- Contracts: domain status `simulated` (never a fill; dedicated pill tone), EventType `execution.order.simulated`, ack events now carry `CommandAckPayload` (resolves the Phase 01/02 shortcut). C# mirrors 1:1 (`Execution.cs`), observer v0.2.0 producer‖consumer with `EXECUTION_MODE="observe"` constant and zero trade calls.
- Store: `ExecutionCommandView` + `commands` map (sent→retried/acknowledged/rejected/expired/failed/reported), signal lifecycle wiring; 5s ack timeout → one same-id retry (DUPLICATE = confirmation) → failed; rejected/expired never produce a fill (tested).
- Gates: lint clean, source `tsc` exit 0, 56 Vitest (9 new), dotnet build 0/0 + 14/14 xUnit, `py_compile` OK. ADR 0010.

### Changed - Phase 09 Closed (validated live, idempotency exercised for real)

- User's live run confirmed the full loop: signals both sides → risk-sized volumes (0.12–0.28 lot tracking stop distance) → ACCEPTED acks → `simulated` reports. A cockpit restart without restarting the observer replayed counter-based ids → the agent's persistent dedup set answered DUPLICATE and refused to re-simulate — the specified behavior, exercised in real conditions.
- Fixes folded in at closure: session-unique signal/command ids (`sig-{runId}-{seq}`; cross-session/tab collisions eliminated) and ack confirmations no longer overwrite the risk-decision text on signal cards.

### Current Next Step

Phase 10 - Persistence (PostgreSQL/Timescale), before any paper trading: phase-start (design → validation → code) for storing commands, decisions, acks, reports, candles, and audit traces.

## 2026-07-09

### Added - /signals Audit Workspace (Phase 07 addendum)

- Built the full `/signals` page (was a stub) as the detailed audit/tracking view: master-detail with a signal list + a detail panel showing the lifecycle stepper, context/bias/strategy, entry/stop/target/side, the associated `RiskDecision` (approved/rejected, `approvedVolume`, reason, gates), and matching execution fills. Command Center Signal Queue stays the summary.
- Data enrichment: read-model `StrategySignal` += `entryPrice`/`stopLoss`/`takeProfit`; `RiskDecisionView` += `gates`; store keeps `riskDecisions` per signal (set on `risk.decision.made`); mock seed signals carry levels.
- `components/cockpit/signals-workspace.tsx`. Verified: lint, source `tsc`, build, 47 tests.

### Added - Phase 07 Signal → Risk Review Wiring

- Added the Phase 07 design (`project/phases/phase-07-design.md`), validated by the user, then implemented the same day.
- Replaced the mock's faked signal approvals (`score >= 7`) with real `RiskDecision`s from the Phase 06 `evaluateSignalRisk` (sizing + gates + lockout). The mock is now a mini strategy: `lib/mock/signals.ts` emits domain `StrategySignal`s from the computed `MarketContextState`.
- Added the audit-grade contract `risk.decision.made` + `RiskDecisionMadePayload` + `RiskDecisionView` (resolves the Phase 02 shortcut where risk decisions reached the dashboard only via `SignalUpdatedPayload`).
- Added projections `toStrategySignalReadModel` / `toRiskDecisionView`; `initial-snapshot.mockRiskContext()` exposes the domain `RiskState`; store handles `risk.decision.made`; `mock-client.advanceSignals` rewritten (create → review → decide → fill @ approvedVolume).
- Verified: lint clean, source `tsc` exit 0, build compiles, 47 Vitest tests (3 new). Legacy `risk.command.approved/rejected` events remain in the contract, unused by the mock.

### Added - Phase 06 Risk & Prop Firm Mode

- Added the Phase 06 design (`project/phases/phase-06-design.md`), validated by the user, then implemented the same day.
- Added `lib/risk/` — the first risk engine (pure TS, imports only `lib/domain`): one gate per FTMO guard (daily loss, max drawdown, open risk, max trades, consecutive losses, spread, session; news stub), `evaluateRiskState` (normal/warning/locked + lockout), `evaluateSignalRisk`→`RiskDecision` (built + tested, not wired), `defaultRiskPolicy`.
- Added `toRiskStatusReadModel` projection; wired the mock (`mockRisk` computes) and live (`LiveRealtimeClient` captures a session baseline and computes risk from real account/positions/spread/session). Risk Status panel + risk KPI tiles now render computed values in mock and live.
- Honesty: `RiskState`/`RiskStatus` `tradesToday`/`consecutiveLosses` are now `number | null` (observe → "n/a"); positions without a stop-loss are excluded from open-risk.
- Added `ADR 0008 - Risk Engine In TypeScript (MVP)` and `context/engineering/risk_engine_mvp.md`.
- Verified: lint clean, source `tsc` exit 0, build compiles, 44 Vitest tests (15 new). Engine v0.1 — a hypothesis, not a validated edge.

### Added - Phase 05 Live Observe Prototype (MT5 → cockpit, read-only)

- Added the Phase 05 design (`project/phases/phase-05-design.md`), validated by the user (Python producer, XAUUSDm, local run OK), then implemented the same day.
- Added `tools/mt5-observer/` — a Python `MetaTrader5` producer that reads real Exness demo data (account, positions, ticks, M15 candles) and streams lean `mt5-wire` JSON over a local WebSocket. **Strictly read-only** (`observe` mode, no `order_send`); no credentials needed.
- Added `lib/realtime/mt5-translate.ts` (pure lean→read-model mappers, tested) and `lib/realtime/live-client.ts` (`LiveRealtimeClient`: WS, connection-state machine, heartbeat watchdog, real M15 candles → Phase 04 engine → Market Context).
- `lib/realtime/provider.tsx` selects mock vs live via `NEXT_PUBLIC_REALTIME_SOURCE` (mock stays default); `top-command-bar.tsx` badge is now environment-aware (MOCK/DEMO/PAPER/LIVE). Added `.env.example`.
- Added `ADR 0007 - Live Observe Prototype` (browser-side translation is a documented shortcut; production keeps the .NET gateway + MQL5 agent) and `context/realtime/live_prototype.md` (runbook + what's real vs. not).
- Verified: lint clean, `tsc --noEmit` exit 0, build passes (13 routes), 29 Vitest tests, `py_compile` OK. Real end-to-end run is the user's step. Honest gaps: risk/signals/execution not produced yet → empty states.

### Added - Phase 04 ICT/SMC Engine MVP

- Added the Phase 04 technical design (`project/phases/phase-04-design.md`), validated by the user, then implemented the same day.
- Added `lib/analysis/` — the first server-side domain engine (pure TypeScript, imports only `lib/domain`): swings, market structure (BOS/CHOCH), liquidity (equal highs/lows, PDH/PDL, swept), PD arrays (FVG + order blocks), sessions, bias + premium/discount, weighted scoring, and the `analyzeMarketContext` orchestrator emitting `MarketContextState`.
- Added `lib/contracts/projections.ts` (`MarketContextState → MarketContext` read model) and `lib/mock/candles.ts` (deterministic synthetic series); rewired the mock so the Market Context panel renders computed output while staying MOCK-badged. No UI/seam/store changes.
- Introduced Vitest (dev-only) + `test` script + `vitest.config.ts`; 23 deterministic-fixture tests. Runtime dependencies remain zero.
- Added `ADR 0006 - ICT/SMC Analysis Engine In TypeScript (MVP), Vitest For Domain Tests` and `context/engineering/analysis_engine_mvp.md` (scope, deferred engines, no-look-ahead rule).
- Verified: lint clean, `tsc --noEmit` exit 0, build passes (13 routes), all tests pass. Engine is v0.1 — a hypothesis, not a validated edge.

### Changed - Phases 01-03 Closure

- Reviewed and closed Phases 01 (Frontend Foundation), 02 (Domain Model MVP), and 03 (MT5 Agent Spec) together at the user's request; the review decision discharged Phase 01's last-open visual walkthrough.
- Re-verified at closure (no code changed): `npm run lint` clean, `tsc --noEmit` exit 0, `npm run build` compiles (13 static routes); all deliverable artifacts confirmed present.
- Fixed the gateway-location decision: the WebSocket Gateway waits for the ASP.NET Core backend — no interim Node/Next WebSocket dev server.
- Updated the three phase files (closure sections), `project_state.md` (phases closed, Next Up rewritten, decision promoted, open questions pruned), and `handoff.md`.

### Changed - Phases 04 + 05 Closed

- Closed Phase 04 (ICT/SMC Engine) and Phase 05 (Live Observe Prototype) on 2026-07-08 after the user validated the live run against their real Exness demo (account 436634705, XAUUSDm): DEMO badge + connected, real balance/positions/ticks, engine-computed market context on real M15 candles.
- Fixed at closure: `kpi-strip` blanked entirely when `risk` was null (live mode); now degrades gracefully so real equity/positions/agents render.
- Updated phase files (closure sections), `project_state.md`, `roadmap.md` (statuses), `handoff.md`.
