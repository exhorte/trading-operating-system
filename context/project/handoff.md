# Handoff Log

For concise chronological change tracking, also read `project/changelog.md`.

## 2026-07-09 - Phase 07 Implementation (Signal → Risk Review Wiring)

Chosen by the user to stabilise the business flow before the backend: replace the mock's faked `score >= 7` approvals with real, testable `RiskDecision`s, on clean contracts. Design validated (new `risk.decision.made` event; mock becomes a mini strategy; live signals out of scope).

Built:

- Contract `risk.decision.made`: `envelope.ts` EventType, `RiskDecisionMadePayload` + `EventPayloadMap` entry, `RiskDecisionView` read model (`snapshots.ts`).
- Projections `toStrategySignalReadModel(signal, decision?)` and `toRiskDecisionView(decision)` (+ tests).
- `lib/mock/signals.ts` — mock mini strategy: domain `StrategySignal` from the computed `MarketContextState` (side ← bias, fixed-distance stop/target, carries the frozen context).
- `initial-snapshot.mockRiskContext()` — exposes the domain `RiskState` + policy + balance so the panel and the signal review share one state (session set to open NY-AM so approvals flow, else a blocked entry gate would reject everything). Seed `sig-014` flipped off `risk_review`.
- Store handles `risk.decision.made` (updates the signal). `mock-client.advanceSignals` rewritten: create a domain signal → next tick reviews it via `evaluateSignalRisk` → emit `risk.decision.made` → on approval, fill @ `approvedVolume`.

Verified: lint clean, source `tsc` exit 0 (temp tsconfig excluding the dev server's `.next/dev/types`), build compiles, 47 Vitest tests (3 new). Runtime sanity: bullish context → buy signal → approved, 2.02 lot at 1% risk, mode normal.

Key handoff:

- The Signal → Risk Review loop is now real in the mock; the decision-grade record (`RiskDecision`) reaches the dashboard via `risk.decision.made` (resolves the Phase 02 shortcut). Legacy `risk.command.approved/rejected` events remain in the contract, now unused by the mock.
- Live/observe still has no signals (no strategy engine); this loop is mock-only until a real strategy engine or the backend exists.
- Not yet committed at time of writing.

## 2026-07-08 - Phase 06 Implementation (Risk & Prop Firm Mode)

Chosen to fill the last empty panel (Risk Status) the user saw in the Phase 05 live view. Design validated (scope = panel + gates; `evaluateSignalRisk` built+tested but not wired; live = session baseline + honest "n/a").

Built `lib/risk/` (pure, imports only `lib/domain`): `policy` (`defaultRiskPolicy`, `WARNING_THRESHOLD`), `types`, `open-risk` (excludes sl≤0 positions), `gates` (one pure fn per FTMO guard; "n/a" on unknown input), `evaluate` (`evaluateRiskState` → normal/warning/locked + lockout), `sizing` (`evaluateSignalRisk`→`RiskDecision`; NOT wired), `index`. Projection `toRiskStatusReadModel(state, policy)` added. Made `RiskState`/`RiskStatus` `tradesToday`/`consecutiveLosses` `number | null`; panel renders "n/a". Wired mock (`mockRisk` computes) + live (`LiveRealtimeClient` captures a session baseline, computes risk from real account/positions/spread/session; trade-history gates "n/a").

Real edge case handled (from the Phase 05 run): the demo position had SL 0.00 → excluded from open-risk instead of a nonsensical `|entry−0|` blow-up.

Verified: lint clean, source `tsc` exit 0 (via a temp tsconfig excluding the concurrent dev server's `.next/dev/types`), build compiles, 44 Vitest tests (15 new). Engine is v0.1 — a hypothesis. ADR 0008, `context/engineering/risk_engine_mvp.md`, phase-06 files.

Key handoff:

- Same law as ADR 0006: `lib/risk` imports only `lib/domain`; projection lives in `lib/contracts`.
- Account-lockout gates (daily loss/drawdown/max trades/consecutive) drive `locked`; spread/session/open-risk are entry gates.
- Deferred (ADR 0008): news calendar, trailing drawdown, profit-target lockout, Friday/Sunday blocks, cooldown, ATR gate, multi-symbol sizing (generalise the XAUUSD 100 USD/point factor via `SymbolMetadata`), and wiring `evaluateSignalRisk` into Signal → Risk Review → Execution.
- Not yet committed at time of writing.

## 2026-07-08 - Phases 04 + 05 Closed

Both closed after the user's live validation against their real Exness demo (account 436634705, XAUUSDm): the cockpit showed DEMO + connected, real balance/equity/positions, live ticks, agent `mt5-observer-1`, and a market context computed by the Phase 04 engine on real M15 candles ("Downtrend after CHOCH", PDH, bearish FVG/OB, 5/10). One fix folded into the Phase 05 commit: `kpi-strip` blanked the whole strip when `risk` was null (live mode) — now it degrades gracefully. Gates green. Phase 04 = `298480a`, Phase 05 = `4f56064`. Next: Phase 06 (Risk & Prop Firm Mode) in phase-start.

## 2026-07-08 - Phase 05 Implementation (Live Observe Prototype)

Triggered by the user wanting to validate the connection chain against their real Exness demo ($1000). Two things were established first: (1) **never share account credentials** — a local reader attaches to the already-authenticated terminal, no password needed; (2) there were **no live connections built yet** — the cockpit was mock-only, Phase 03 was spec-only. So this is a build phase, not a test. The user chose the realtime prototype over the roadmap's Risk phase, then validated the design (Python producer, XAUUSDm, local run OK).

Built:

- `tools/mt5-observer/mt5_observer.py` — Python `MetaTrader5` producer, **strictly read-only** (`observe` mode, no `order_send`/trade calls). Emits lean `mt5-wire` JSON (hello, account/positions snapshots, ticks, M15 candles, heartbeat) over `ws://localhost:8765`. Plus `requirements.txt` + `README.md` (runbook + safety).
- `lib/realtime/mt5-translate.ts` — pure lean→read-model mappers (+ 6 tests).
- `lib/realtime/live-client.ts` — `LiveRealtimeClient` implementing the `RealtimeClient` seam: WS, `connecting→connected→stale→reconnecting` state machine, heartbeat watchdog, candle window → Phase 04 engine → Market Context. Read-only (never sends).
- `lib/realtime/provider.tsx` — selects mock vs live via `NEXT_PUBLIC_REALTIME_SOURCE` (mock default). `components/shell/top-command-bar.tsx` — env-aware badge (MOCK/DEMO/PAPER/LIVE) + real symbol.
- `.env.example`, ADR 0007, `context/realtime/live_prototype.md`, phase-05 files.

Verified here: lint clean, `tsc --noEmit` exit 0, build passes (13 routes), 29 Vitest tests (10 files), `python -m py_compile` OK. **The real end-to-end run is the user's next step** (needs their Windows terminal + demo, which this environment can't do).

Key handoff:

- Browser-side translation is a **deliberate prototype shortcut** (ADR 0007). Production keeps the .NET gateway (ADR 0005) + MQL5 EA/sidecar (Phase 03); `live-client.ts` + `mt5-translate.ts` are throwaway/reference. The `mt5-translate` mappers are portable and can seed the .NET gateway.
- Honest gaps in live mode: risk/signals/execution/drawdown-baseline are NOT produced (no engines yet) → empty/zero states, never fake numbers. This is why **Risk & Prop Firm Mode** is the natural next engine — it makes the observed account's risk panel real.
- Runbook: `tools/mt5-observer/README.md`. To enable: run the producer, then `$env:NEXT_PUBLIC_REALTIME_SOURCE="live"; npm run dev`.
- Not yet committed at time of writing (Phase 04 was committed as `298480a`).

## 2026-07-08 - Phase 04 Implementation (ICT/SMC Engine MVP)

Phase 04 was designed, validated by the user (build the ICT/SMC engine now; engine home = TypeScript in this repo; MVP scope confirmed), and implemented the same day.

Built:

- `lib/analysis/` — pure engine importing only `lib/domain`: `config`, `types`, `swings`, `structure` (BOS/CHOCH), `liquidity` (equal highs/lows, PDH/PDL, swept flags), `pd-arrays` (FVG + order blocks), `sessions`, `bias` (+ premium/discount location), `scoring` (weighted `ScoreComponent[]`), `market-context` (orchestrator `analyzeMarketContext`), `index` barrel, `test-helpers`, and colocated `*.test.ts`.
- `lib/contracts/projections.ts` — `toMarketContextReadModel(MarketContextState) → MarketContext` (the only humanisation point) + test.
- `lib/mock/candles.ts` — deterministic seeded `mockCandles()` + `nextCandles()` live-advance.
- Rewired `lib/mock/initial-snapshot.ts` (`mockMarketContext` computes) and `lib/realtime/mock-client.ts` (`emitContextUpdate` advances candles and re-runs the engine). Panel/seam/store/event contract unchanged.
- Vitest (dev-only) + `vitest.config.ts` + `"test": "vitest run"`.
- Docs: ADR 0006, `context/engineering/analysis_engine_mvp.md`, `phase-04-ict-smc-engine.md`, `phase-04-design.md`.

Verified: lint clean, `tsc --noEmit` exit 0, `npm run build` passes (13 routes), 23 Vitest tests across 9 files. Runtime sanity on the mock series: `bias=bullish | Uptrend after BOS | BOS above 3,325.36 | PDL 3,299.98 | bullish FVG + OB | score 5/10`.

Key handoff:

- Dependency law extended: `lib/analysis` imports only `lib/domain`; the domain→read-model projection lives in `lib/contracts`, never in the engine. Keep it that way.
- No-look-ahead is a hard invariant (asserted in tests) — preserve it for Phase 07 backtesting.
- Engine is `v0.1`, a hypothesis. Tolerances are raw price units; a later revision should derive them from ATR/tickSize. Deferred engines (SMT, news/macro, OTE, entry/trade-management) are listed in `analysis_engine_mvp.md`; Bias/Scoring are the extension points.
- Next recommended action: user review of the Market Context panel now showing computed output (`npm run dev`), then Phase 05 (Risk & Prop Firm Mode) as pure TS services following the same engine-first pattern — also unblocked by the backend. The realtime prototype remains gated on ASP.NET Core.

## 2026-07-08 - Phases 01-03 Review And Closure

The user chose to review and close Phases 01 (Frontend Foundation), 02 (Domain Model MVP), and 03 (MT5 Agent Spec) together rather than start the next build. That decision serves as the review sign-off and discharges the one item that was still blocking Phase 01 (a human visual walkthrough in `npm run dev`).

Re-verified at closure (no code changed — verification only):

- `npm run lint` clean.
- `tsc --noEmit` exit 0.
- `npm run build` compiles, 13 static routes (was reported as 11 earlier; `/` and `/_not-found` now counted in the 13).
- All Phase 01/02/03 deliverable artifacts confirmed present on disk (`lib/domain/*`, `lib/contracts/*` incl. `mt5-wire.ts`, `lib/realtime/*`, `context/realtime/mt5_wire_protocol.md`, `context/domain/domain_model_mvp.md`, ADRs 0004 and 0005).

Decision fixed at closure: the WebSocket Gateway waits for the ASP.NET Core backend — no throwaway Node/Next WebSocket dev server. Recorded in `project_state.md` (Decisions Already Made) and the resolved open question.

Updated: the three phase files (closure sections), `project_state.md` (phases now closed, Next Up rewritten, gateway decision promoted, open questions pruned), `changelog.md`, this log.

Key handoff:

- No phase is active. The recommended next phase is the first realtime prototype in `observe` mode against `mt5-wire.ts`, but it is now gated on standing up the ASP.NET Core backend surface first (that is where the gateway will live). Start it with the phase-start procedure.
- Two Phase 01→02 reconciliation shortcuts are still open and should be addressed when the store adopts `EventPayloadMap`: the mock publishes `execution.command.acknowledged` as an ExecutionReportPayload (canonical is CommandAckPayload), and risk decisions reach the dashboard only as SignalUpdatedPayload (decision-grade record is `RiskDecision`).

## 2026-07-07 - Phase 03 Specification

Phase 03 (MT5 Agent Spec) was specified after the user fixed three load-bearing decisions (see `project/phases/phase-03-design.md`):

1. Two transport worlds: MT5 edge speaks lean WSS + versioned JSON; a .NET WebSocket Gateway translates to the internal `Envelope<T>` + domain models; SignalR is dashboard-side only.
2. Full command loop from sprint 1, gated by execution modes `observe` (SIMULATED, no broker) → `paper` (demo) → `live` (FTMO); same code, config-only switch; backend `ExecutionAdapter` abstraction.
3. External sidecar bridge for MQL5 networking (EA ↔ sidecar over pipe/socket; sidecar ↔ gateway over WSS).

Built (documentation + wire contracts only — no EA/sidecar/gateway code in this repo):

- `context/realtime/mt5_wire_protocol.md` — lean edge protocol, examples, execution modes, inbound/outbound gateway translation tables.
- `lib/contracts/mt5-wire.ts` — canonical lean-edge TS types (`Mt5*Message`/`Mt5*Command`, `Mt5ExecutionMode`, inbound/outbound unions). Lint + typecheck pass; not imported anywhere yet.
- `context/realtime/mt5_agent_realtime_lifecycle.md` — extended with sidecar topology and execution modes.
- `context/adr/0005-mt5-lean-wire-and-gateway.md`.

Key handoff:

- The lean edge protocol is intentionally simpler than the internal envelope; the gateway is the adapter. Keep `mt5-wire.ts` and the internal `lib/contracts`/`lib/domain` in sync via the mapping tables.
- `time` at the edge is epoch **milliseconds** (refined from the user's seconds example) so ticks stay ordered; the gateway converts to ISO.
- Next recommended action: build the first WebSocket Gateway + a mock sidecar/producer speaking `mt5-wire.ts` in `observe` mode, end-to-end into the cockpit — after deciding whether the gateway runs as a Node/Next dev server or waits for ASP.NET Core. Or close Phases 01-03 with a user review first.

## 2026-07-07 - Phase 02 Implementation

Phase 02 (Domain Model MVP) was designed (`project/phases/phase-02-design.md`) and implemented in direct continuation at the user's request ("analyse where we stopped and continue").

Built:

- `lib/domain/`: canonical portable schemas — primitives (ids, timestamps, timeframe, side/bias/session), market (SymbolMetadata, Tick, Candle, SpreadSample, SessionWindow), account (BrokerAccount, TradingAccount), analysis (LiquidityLevel, FairValueGap, OrderBlock, StructureShift, MarketContextState), risk (RiskPolicy, RiskMode, RiskGateResult, RiskState, RiskDecision), strategy (SignalStatus, StrategySignal), execution (Order, Position, Trade, ExecutionCommand union, CommandAck, ExecutionReport, ExecutionAgent)
- `lib/contracts/commands.ts`: execution command payloads, CommandAckPayload, RealtimeSubscription, SubscriptionTopic
- `lib/contracts/events.ts`: payloads for all remaining event families plus `EventPayloadMap` (exhaustive over all 43 `EventType`s) and `KnownEnvelope<T>`
- `lib/contracts/enums.ts`: now re-exports domain vocabulary; `RiskState` kept as legacy alias of domain `RiskMode`
- `context/domain/domain_model_mvp.md` (layering, portability rules, .NET/MQL5 mapping, traceability chain) and ADR 0004 (TypeScript as canonical schema source for the MVP)

Verified: lint, `tsc --noEmit`, and production build pass; zero UI/component changes, zero new dependencies.

Key handoff:

- Dependency direction is law: `components` → `lib/realtime` → `lib/contracts` → `lib/domain`; the domain imports nothing.
- Known Phase 01 shortcuts to reconcile when the store adopts `EventPayloadMap`: mock publishes `execution.command.acknowledged` as an ExecutionReportPayload (canonical is CommandAckPayload), and risk decisions reach the dashboard only as SignalUpdatedPayload (decision-grade record is `RiskDecision`).
- Next recommended action: user review of Phase 01 cockpit + Phase 02 schemas, then Phase 03 (MT5 Agent Spec) starting from `context/realtime/mt5_agent_realtime_lifecycle.md`, or first decide the realtime prototype question (Node WebSocket vs ASP.NET Core SignalR).

## 2026-07-06 - Project Brain Bootstrap

Created initial `.claude/` and `context/` structure for the Trading Operating System Algorithmique.

Source material analyzed:

- ICT/SMC framework notes
- platform architecture notes
- recommended stack notes
- FTMO EA configuration objectives
- `Ultimate_ICT_Gold_Scalper_v4.0.mq5`

Key handoff:

- The project starts from a blank Next.js app.
- The next useful phase is dashboard foundation, not strategy execution.
- The EA should be preserved as knowledge and later refactored into an MT5 execution agent.
- Before building real execution, define contracts and risk gates.

Next recommended action:

- Start Phase 01 with a design for the dashboard shell and mock data contracts.

## 2026-07-06 - WebSocket-First Architecture Adaptation

The project direction was updated to use WebSocket/SignalR as the primary infrastructure instead of a classic API-first architecture.

Updated:

- system overview
- backend plan
- stack
- roadmap and phases
- frontend plan
- infrastructure and monitoring plans
- security principles
- Claude prompts
- quality gates

Added:

- `context/realtime/`
- `context/adr/0003-websocket-first-infrastructure.md`

Key handoff:

- Trading flows must be modeled as realtime events, commands, acknowledgements, and reports.
- REST/HTTP remains allowed only for secondary workflows such as health, auth/bootstrap, static configuration, imports/exports, admin, and documentation.
- Phase 01 dashboard should be designed around mock realtime subscriptions, not API polling.

## 2026-07-06 - Phase 01 Implementation

Phase 01 (Frontend Foundation) was designed, validated by the user (zero new runtime dependencies confirmed), implemented, and verified.

Built:

- `(cockpit)` route group: Command Center plus market-context, signals, positions, risk, journal, replay, agents, backtests, settings (stubs with honest empty states), `loading.tsx`, `error.tsx`
- app shell: icon rail, collapsible sidebar, top command bar (MOCK badge, WebSocket status, inert emergency stop)
- `lib/contracts/`: TypeScript mirrors of the realtime envelope, event families, and dashboard read models
- `lib/realtime/`: `RealtimeClient` interface, `CockpitStore` reducer over enveloped events, `MockRealtimeClient` (snapshot + events + heartbeats + watchdog stale detection + scripted outage/resync), React provider/hooks
- `lib/mock/`: enveloped XAUUSD/FTMO-style generators
- 8 Command Center panels and the dark cockpit theme tokens

Verified: lint and build pass (11 routes), production smoke test renders all panels and stub pages. The WS badge cycles connected → stale → reconnecting → connected roughly every 55s under `npm run dev`.

Key handoff:

- UI must keep depending on the `RealtimeClient`/`CockpitStore` seam; the future SignalR client replaces `MockRealtimeClient` without touching components.
- `lib/contracts/` is the seed of Phase 02; keep it in sync with `context/realtime/event_contracts.md`.
- Next recommended action: user visual walkthrough, then start Phase 02 (Domain Model MVP) with a design.

## 2026-07-06 - Phase 00 Verification And Closure

Phase 00 was audited against its acceptance criteria and closed.

Verified:

- The project brain loads correctly from `.claude/` and `context/`.
- `../NOTES/` is fully indexed in `context/knowledge/source_notes_index.md` (all 8 source files).
- The EA is documented as knowledge source and future agent, not the platform brain.
- Next phase, risk constraints, and governance are explicit.
- `npm run lint` passes on the Next.js baseline.

Fixed at closure:

- The entire project brain was untracked in git (only the Create Next App commit existed). Committed `.claude/`, `context/`, and the `CLAUDE.md` update so the memory is durable.
- Renamed raw-exported visual reference images in `context/templates/` to descriptive names (`reference-dashboard-overview.png`, `reference-trades-table.png`, `reference-trade-replay.webp`) and updated `context/frontend/visual_reference_analysis.md`.

Next recommended action:

- Start Phase 01 with the design procedure in `.claude/commands/phase-start.md`.

## 2026-07-06 - Visual Reference Analysis

The visual references added to `context/templates/` were analyzed and converted into frontend guidance.

Added:

- `context/templates/README.md`
- `context/frontend/visual_reference_analysis.md`
- `context/frontend/final_interface_spec.md`

Key handoff:

- The UI should be a dark, dense, operational trading cockpit.
- Use the references for patterns only: left navigation, top command bar, KPI strip, P&L calendar, dense trade table, replay workspace.
- Do not copy TradeZella branding or exact layouts.
- Adapt the final render to this platform's priorities: WebSocket state, risk gates, MT5 agent health, ICT/SMC market context, signals, execution reports, and auditability.
