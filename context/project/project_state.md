# Project State

## Current Status

The repository is a fresh Next.js project named `trading_operating_system_algorithmique`.

Initial project brain has been created from the source notes in `../NOTES/`.

The project brain has since been refined with:

- a WebSocket/SignalR-first architecture decision
- realtime event/command/report contracts
- MT5 agent realtime lifecycle guidance
- dashboard realtime subscription guidance
- visual reference analysis from `context/templates/`
- final interface specification for the trading cockpit

## Active Product Direction

Build a Trading Operating System Algorithmique where:

- Next.js provides the dashboard/control cockpit.
- Backend services will host the trading intelligence.
- WebSocket/SignalR is the primary communication infrastructure.
- The ICT/SMC framework becomes a reusable analysis engine.
- The MT5 EA becomes an execution and telemetry agent.
- FTMO-style risk controls are core constraints.

## Current Phase

Phase 00 - AI Project Brain Bootstrap: closed 2026-07-06.

Phase 01 - Frontend Foundation: closed 2026-07-08. Implemented 2026-07-06 after validated design (`project/phases/phase-01-design.md`). The cockpit shell, Command Center, typed contracts, and mock realtime client exist. The user's review-and-close decision discharged the last-open visual walkthrough.

Phase 02 - Domain Model MVP: closed 2026-07-08. Implemented 2026-07-07 (`project/phases/phase-02-design.md`). Canonical portable schemas live in `lib/domain/`; `lib/contracts/` became the wire layer with full `EventPayloadMap` coverage; ADR 0004 records TypeScript as the MVP schema source. Zero UI changes.

Phase 03 - MT5 Agent Spec: closed 2026-07-08. Specified 2026-07-07 (`project/phases/phase-03-design.md`). Deliverables: `context/realtime/mt5_wire_protocol.md`, `lib/contracts/mt5-wire.ts`, extended `mt5_agent_realtime_lifecycle.md`, ADR 0005. Documentation + wire contracts only; the EA/sidecar/gateway are not built here.

Phases 01-03 were reviewed and closed together on 2026-07-08. Re-verified at closure: `npm run lint` clean, `tsc --noEmit` exit 0, `npm run build` compiles (13 static routes); all deliverable artifacts confirmed present.

Phase 04 - ICT/SMC Engine MVP: closed 2026-07-08 (committed `298480a`; `project/phases/phase-04-design.md`). Pure TypeScript analysis engine in `lib/analysis/` (imports only `lib/domain`): swings → structure (BOS/CHOCH) → liquidity → PD arrays (FVG/OB) → session → bias → weighted scoring → `MarketContextState`; projection in `lib/contracts/projections.ts`. Validated on both mock and (Phase 05) real candles. Engine is v0.1 — a hypothesis, not a validated edge.

Phase 05 - Live Observe Prototype: closed 2026-07-08 (committed `4f56064`; `project/phases/phase-05-design.md`). Read-only path streaming **real** Exness demo data into the cockpit. `tools/mt5-observer/mt5_observer.py` (Python `MetaTrader5`, read-only, `observe`) emits lean `mt5-wire` JSON over `ws://localhost:8765`; `lib/realtime/live-client.ts` translates it via pure mappers (`lib/realtime/mt5-translate.ts`) and feeds real M15 candles to the Phase 04 engine. Opt-in via `NEXT_PUBLIC_REALTIME_SOURCE=live` (mock default); badge reads DEMO. Browser-side translation is a documented prototype shortcut (ADR 0007). **Validated live** by the user (account 436634705, XAUUSDm). KpiStrip fixed to degrade gracefully when `risk` is null.

Phase 06 - Risk & Prop Firm Mode: implemented 2026-07-08 (`project/phases/phase-06-design.md`, validated first). Pure TS risk engine in `lib/risk/` (imports only `lib/domain`): one pure gate per FTMO guard (daily loss, max drawdown, open risk, max trades, consecutive losses, spread, session; news stub) → `evaluateRiskState` derives normal/warning/locked + lockout → `toRiskStatusReadModel` projection fills the Risk Status panel + risk KPI tiles in mock **and** live. `evaluateSignalRisk`→`RiskDecision` built + tested but not wired. Honesty: `tradesToday`/`consecutiveLosses` are `number | null` (observe → "n/a"); no-SL positions excluded from open-risk. Verified: lint, source `tsc`, build, 44 tests. Engine v0.1 — a hypothesis. ADR 0008. Awaiting user review before closure.

Phase 06 - Risk & Prop Firm Mode: closed 2026-07-10 (committed `6f1a0c9`). Pure TS risk engine in `lib/risk/`; validated in the live cockpit against the user's real Exness demo, then exercised end-to-end by Phase 07.

Phase 07 - Signal → Risk Review Wiring: closed 2026-07-10 (commits `3f4208c`, `d455a72`, `59fa86e`). The mock is a mini strategy emitting domain `StrategySignal`s from the computed `MarketContextState`; the real `evaluateSignalRisk` rules on each (sizing + gates + lockout) on the audit-grade `risk.decision.made` contract. The full `/signals` audit workspace shows lifecycle, levels, RiskDecision (volume, reason, gates), and fills; the Command Center stays the summary. Rotating mock scenarios (wide spread, closed session) produce real rejections, with the Risk panel synced to the same state the review used. Live/observe signals remain out of scope (no strategy engine there).

Phase 08 - ASP.NET Core Backend Bootstrap: closed 2026-07-11 (committed `0977175`; validated live by the user — full chain MT5 → Python observer → .NET gateway (server-side translation) → SignalR → cockpit on the real Exness demo). .NET 10 solution under `backend/`: Contracts (C# mirrors), Gateway (`Mt5WireTranslator` + `Mt5ObserverClient`), Host (SignalR `CockpitHub`, `/health`, CORS), 7 xUnit tests mirroring the TS translator tests. Frontend: `SignalRRealtimeClient` behind the seam (source `backend`; `@microsoft/signalr` = first runtime dep); TS engines still run client-side on relayed candles/state. The superseded `LiveRealtimeClient` was deleted at closure; `mt5-translate.ts` + tests stay as the TS reference the C# mirrors.

Phase 09 - Execution Bridge (observe/SIMULATED): closed 2026-07-11 (committed `57e96b1` + closure fixes; user's 10-point spec, design validated first). Full command loop at zero risk, **validated live**: approved `RiskDecision` → `buildPlaceOrderCommand` (volume = approvedVolume) → `CockpitHub.SubmitCommand` (observe-mode guard) → lean `execution.order` → observer validation/dedup → `execution.ack` + `execution.report SIMULATED` (no trade call exists anywhere) → canonical `CommandAckPayload` + `execution.order.simulated` → store lifecycle. The live run exercised real idempotency (restart replayed ids → DUPLICATE acks, no double fill), which surfaced and fixed two defects: session-unique ids (`sig-{runId}-{seq}`) and confirmations no longer overwrite the risk-decision text. Gates: lint/tsc/56 Vitest, 14/14 xUnit, py_compile. ADR 0010.

Phase 10 - Persistence: closed 2026-07-12 (committed `bc48110`). TimescaleDB via docker-compose (host port **5433**), idempotent embedded schema (8 tables incl. hypertables + JSONB `envelopes` audit), never-blocking `PersistenceWriter`, hub `PublishEvent` (whitelisted, source of truth for signals, multi-tab consistent), `/api/audit/recent`. **Validated live**: thousands of envelopes persisted, 0 dropped, endpoint 200 after the Dapper timestamptz→DateTime reader fix (+ integration test). The persistence precondition before paper trading is met.

Phase 11 - Backtesting MVP: closed 2026-07-14 (committed `d7d9106`). Pipeline validated on the first real run (`bt-mrkx74n5-500ff1f8`: 25,999 M15 candles over ~13 months, 3,209 signals, 1,261 trades). **Baseline result is honestly negative: win rate 32.31%, expectancy −0.02R, cumulative −21.55R, max 21 consecutive losses** — engine v0.1 has no edge on this period even before costs; statistically near-random for a stub strategy. No paper trading in this state (user decision). The negative number IS the deliverable: the "backtest before confidence" gate now measures instead of hoping.

Phase 12 - Backtest Diagnostics & Strategy Refinement: **Part A (tooling) delivered 2026-07-14** (`project/phases/phase-12-diagnostics.md`, ADR 0013). Feature capture (`features jsonb`), `backtest_rejections`, chronological 60/20/20 splits tagged by the runner, pure tested `segments.ts`, `backtest-report.ts` (15 dimensions × split, OOS **locked by tooling** until `--unlock-oos`). Enriched baseline `bt-mrkz8r44-d57578d8` reproduces Phase 11 bit-identically (deterministic).

**Part A findings partially retracted 2026-07-17 — the stub was confounded.** `mockStrategySignal` keyed counter-bias (`seq % 4 === 0`), stop distance (`3.5 + (seq % 4) * 1.5`) and a `−3` score penalty off one counter, so counter-bias trades were *exactly* the 3.5-stop trades with a docked score — one cohort, three labels (the two dimensions are numerically identical in every split). **Surviving**: score 6 is the only bucket positive in both splits; 1–2-bar losses dominate — and the root cause is that the stub fires every 8 bars with no entry trigger and a noise-width stop, i.e. it samples arbitrary moments. **Not attributable**: counter-bias / 3.5-stop bleed (same cohort). **Contaminated**: low-score bleed. **Stop distance is no longer a "train-only mirage"** — 3.5 was consistently worst because it was the probe cohort in disguise. Rejections (100% session filter) unaffected.

**Part B started 2026-07-17 — step 1 (de-confound) done**: `stopDistance` cycles on `seq % 3` (4.0/6.0/8.0) while `counterBias` stays on `seq % 4` (coprime → attributable); `score` is passed through undoctored; `segments.ts` reports the measured stop distance. Gates green (lint, tsc exit 0, 69 Vitest).

**Part B step 2 done — de-confounded baseline read (user, 2026-07-17)**: it does **not** generalize (train ~neutral/slightly positive, validation negative). No dimension — side, sideVsBias, score, stopDistance, BOS/CHOCH, days, sessions — is stable enough to justify a filter. Robust finding stays the 1–2-bar loss concentration; the periodic stub without a setup is the priority structural cause. Inside-FVG is coherent across train+validation but validation n is still low.

**OOS lock leak found (user) + fixed 2026-07-17**: the report headline read the whole-period `backtest_runs` row (1,261 trades / +9.1R incl. 254 OOS trades) while OOS was advertised as locked; the runner console leaked the same way on every run. Guard moved into pure tested code (`reportableTrades` + `summarize`). **`/backtests` page still leaks** — open decision (ADR 0013). Lesson: a display-layer lock must cover every derived figure, not just the hidden section.

**Phase 12 Part B iteration 1 — entry trigger IMPLEMENTED 2026-07-17** (`project/phases/phase-12-iteration-1-design.md`). New pure `lib/strategy/` (ICT FVG-retest, `evaluateTrigger`, stateless by construction) + `lib/analysis/atr.ts` (Wilder ATR). Setup: bias → fresh aligned structure shift → fresh aligned FVG after it → **first** retest → confirmation close (**middle**, fixed a priori) → stop beyond the gap + ATR buffer → **2R unchanged**. Score/sessions/days/Risk Engine/target untouched — the experiment compares the periodic sampler (control) against a real entry condition, nothing else. Runner: `--strategy sampler|trigger` (trigger defaults `--every 1`; sampler path byte-identical); reporter range-buckets the now-continuous `stopDistance`. Gates: lint, tsc exit 0, **86 Vitest** (15 new). Behavioral smoke test (no DB, synthetic walk): 90 signals / 2,668 bars (3.4%), balanced sides, correct 2R geometry — wiring proven, says nothing about edge.

**Iteration 1 result read (user, 2026-07-18; run `bt-mrp973lv-965814cc` vs control `bt-mrowayu5-fdd94b71`, committed `6203da8`)**: the trigger hits its behavioral target — 1–2-bar trades collapse (train 315/756 → 79/496; validation 192/251 → 19/131), validation cum −23R → −3.67R, exp ≈−0.09R → −0.03R, both-touch 23 → 0, **n=131 so the read is powered**. Still negative on validation and costs are unmodeled → **audited, promising experiment; NOT promoted to paper trading** (user decision). The robust train+validation finding is the session split: **NY AM +0.23R (n=270) / +0.21R (n=76) vs London −0.22R (n=226) / −0.36R (n=55)** — the only finding meeting all four rule-3 criteria.

**Pre-run fixes delivered 2026-07-18**: (1) `/backtests` OOS leak closed — `BacktestRepository` recomputes every displayed aggregate in SQL over non-OOS trades (formulas mirror `metrics.ts`, validated value-for-value against the live DB on both Phase-12 runs) and excludes OOS rows from the trade list (individual R multiples are summable); UI shows a 🔒 lock note via `oosTradeCount`; legacy split-less runs count fully (pre-discipline, already read). (2) `evaluateTrigger` now returns `{ signal, setup }` — the EXACT setup traded (fvgLow/High/Size, fvgAgeBars, shiftAgeBars, retestDepthPercent, atr, stopBuffer) recorded as additive feature keys with 3 new report dimensions (`setupFvgSize`/`setupFvgAge`/`setupRetestDepth`); the generic `fvgInside` measures a different notion (entry inside ANY aligned gap — the trigger's confirmation close usually sits outside the gap it retested, hence 3/496). (3) Timeouts documented in `backtest_mvp.md`: no-touch within `--max-bars` → exit at last horizon bar's close; excluded from winRate/avgR, included in expectancy/cumulative; negative timeouts count in loss streaks; iteration 1 has 17% timeouts at +0.4R avg so the win rate understates the arm — a measurement artifact, not a strategy exit.

**Iteration 2 closed 2026-07-18 (run `bt-mrpq4try-b20fc81b`, user-validated)**: the pre-registered invariant test passed **exactly** — train n=270 / +0.23R / +62.04R, validation n=76 / +0.21R / +16.08R, bit-identical to iteration 1's NY AM buckets. Validates the session filter, runner determinism, and no hidden London interaction. Not carried by timeouts alone (validation ≈ +9R decided-only). **⚠ Post-hoc**: NY AM was selected from iteration 1's segmentation and this run reproduces that subset — **not an independent validation; the old train/validation is consumed as development data.**

**Candidate FROZEN 2026-07-18** (`CANDIDATE_CONFIG_2026_07_18` in `lib/strategy/config.ts`, locked by unit test): strategy=trigger, sessions=["new_york_am"], 2R target, middle confirmation, structural stop + 0.5 ATR (floor 1 tick), age caps 12, ATR 14, Risk Engine untouched. **No further filters.** Any change = a new candidate. Standing rules (workflow rule 7): no new filters mined from the consumed dataset; **old OOS never unlocked**; no paper trading before the Phase 13 virgin-holdout verdict AND net-of-costs metrics.

## Next Up

**Phase 13 — Execution Realism & Virgin Holdout: IMPLEMENTED 2026-07-18 per the user's validated decisions. The verdict run is NOT launched** (user rule: review of hashes, bounds, cost profile, and bar first). `project/phases/phase-13-execution-realism-design.md` carries the full record + review checklist.

Delivered: `lib/backtest/holdout.ts` (exact bounds **2024-06-01T00:00Z → 2025-06-06T13:30Z exclusive**, verified against the DB — the dev set's first candle opens exactly at the exclusive bound; ordinary runs CLIP holdout candles by construction, ranges entirely inside are refused), `lib/backtest/costs.ts` (frozen profile: spread **0.26 persisted literally** = max(floor 0.20, observed p95 0.26) — **caveat flagged**: zero NY AM ticks stored, the observation is a single London window (n=3,158, constant 0.26); slippage 0.05/leg; commission 0; `swap: null`; stress 0.30/0.10 informative-only), `lib/backtest/verdict.ts` (the user's bar verbatim where quantified, FAIL-first precedence, 10k seeded bootstrap → bit-reproducible; width-cap 0.40R proposed operationalization), runner `--verdict-holdout` (rejects every override flag; dirty-tree refusal; sha256 hashes of commit/dataset/candidate/cost-profile; single read enforced by the `holdout_verdicts` PRIMARY KEY; audited `holdout_attempts`; **swap invariant** — refusal with zero metrics computed if any trade crosses a 21:00/22:00 UTC rollover while swap is unmodeled, the holdout stays virgin on refusal). Schema += `cost_r`/`net_r_multiple`/`holdout_verdicts`/`holdout_attempts`, applied idempotently to the live DB. Gates: **116 Vitest**, tsc 0, lint clean, dotnet 0/0 + 20/20; guards behaviorally verified (override rejection, dirty-tree refusal, clip inert on dev data).

**User review round 2 (2026-07-18) — bounds and bar VALIDATED DEFINITIVELY** (CI width 0.40R, side rules n≥30, month rule on positive totals, FAIL precedence, seeded 10k bootstrap — may not change after the read). Execution params to resolve BEFORE the single read, tooling delivered:

1. **Spread**: user collects ≥3 (target 5) NY AM sessions of ticks (observer 12:00–16:00 UTC), then `scripts/calibrate-spread.ts` (coverage-guarded: refuses < 3 sessions, verified) prints the literal finals — spreadBase = max(0.26, p95 NY AM), spreadStress = max(0.30, p99 NY AM), slippage 0.05/0.10 — to persist in `costs.ts` + commit. The current 0.26 profile is marked interim.
2. **Swap**: `tools/mt5-observer/inspect_symbol.py` (read-only, py_compile OK) captures swap_mode/long/short/rollover3days/contract/tick size/value + provenance and normalizes to USD/lot/night **respecting swap_mode** (POINTS → tick-value conversion; CURRENCY_DEPOSIT exact only on USD accounts; INTEREST → flagged estimate; else manual-required). The user also confirms swap-free status in the Exness contract specs. Then freeze the SwapSpec (or swap-free) into `costs.ts`.
3. **Import**: `import_history.py` now takes `--from/--to` exact UTC bounds (`--to` exclusive, [from, to) filtered post-fetch) — dataset and hash reproducible bit-for-bit regardless of export time.
4. Then: tests green, clean commit, **Claude presents the final pre-read summary (bounds, hashes, frozen costs, criteria) → user approves → the single `--verdict-holdout` read**. Not before.

## Decisions Already Made

- The platform is not EA-centric.
- MT5 is the first execution connector.
- The EA in `../NOTES/Ultimate_ICT_Gold_Scalper_v4.0.mq5` is a base to analyze, personalize, refactor, and later transform into an agent.
- Next.js is the initial repository surface.
- Long-term backend target is ASP.NET Core with SignalR.
- The platform is WebSocket-first; REST/HTTP is secondary for auth/bootstrap/health/admin workflows only.
- PostgreSQL/TimescaleDB/Redis/RabbitMQ are preferred infrastructure candidates.
- The final interface direction is a dark, dense, operational trading cockpit.
- Visual references are inspiration only and must not be copied as TradeZella clones.
- Phase 01 must model UI data as mock realtime subscriptions, not REST polling.
- Phase 01 shipped with zero new runtime dependencies; shadcn/ui, TanStack Query, and chart libraries are deferred until their first real use case (validated 2026-07-06).
- UI components depend on the `RealtimeClient` seam and `CockpitStore`, never on the mock client directly.
- Canonical domain schemas are portable TypeScript in `lib/domain/` (ADR 0004); `lib/contracts/` is the wire layer and may depend on the domain, never the reverse.
- Dashboard read models (`lib/contracts/snapshots.ts`) are projections for rendering, not domain models; both are legitimate payloads on different channels.
- MT5 edge uses lean WSS+versioned JSON, not SignalR; a WebSocket Gateway translates it to the internal envelope. SignalR is dashboard-side only (ADR 0005).
- The MT5 agent connects through an external sidecar bridge (EA never opens the WSS socket directly); execution runs in `observe`/`paper`/`live` modes, `observe` never touching the broker.
- The WebSocket Gateway waits for the ASP.NET Core backend; no throwaway Node/Next WebSocket dev server will be built (decided 2026-07-08). The first realtime prototype is therefore gated on standing up that backend surface.
- Domain engines are built as pure TypeScript in this repo now (against `lib/domain/`), imports-only-`lib/domain`, and ported to .NET when the backend arrives — the ICT/SMC engine (`lib/analysis/`, ADR 0006) is the first; risk services follow the same pattern. This unblocks server intelligence without waiting for infrastructure.
- Detectors obey a no-look-ahead invariant (a bar's state uses only candles up to that bar) to keep future backtests honest.
- Vitest is the domain test runner (dev-only, ADR 0006); runtime dependencies remain zero. Domain logic ships with deterministic-fixture unit tests.
- Live MT5 access uses a local read-only reader attached to the user's already-authenticated terminal (Python `MetaTrader5`) — **no credentials are ever shared**. The observe prototype's lean→internal translation runs browser-side as a documented, throwaway shortcut (ADR 0007); production keeps a server-side .NET gateway (ADR 0005) + MQL5 EA/sidecar (Phase 03). This carve-out applies to the prototype only; the 2026-07-08 "gateway waits for ASP.NET Core" decision still governs the production path.
- Read-only / `observe` is the mandatory mode for any first connection: no order path, execution controls stay inert.
- The backend lives in this repo under `backend/` as a .NET 10 modular monolith (decided 2026-07-10, ADR 0009); extraction to a sibling repo only if operationally justified later. The gateway translates server-side; the browser-side `LiveRealtimeClient` is superseded and slated for deletion after the backend path is validated live.
- SignalR (`@microsoft/signalr`) is the dashboard's production transport — the first and only frontend runtime dependency to date.

## Open Questions

- ~~Will this remain a single repository containing frontend, backend, EA, and infrastructure, or will the backend live in a sibling repository later?~~ Resolved 2026-07-10: single repo, backend under `backend/` (ADR 0009); revisit only if operationally justified.
- Which auth approach will be selected first: local auth, Supabase Auth, Auth0, or Keycloak?
- Will first market data be mocked, imported from MT5, or pulled from a market data provider?
- Which symbol set is MVP: XAUUSD only, or XAUUSD plus EURUSD/GBPUSD/USDJPY?
- MVP symbol and account scope for the first agent prototype: XAUUSD single account is the working default, not yet formally confirmed.

Resolved 2026-07-08: the WebSocket Gateway waits for the ASP.NET Core backend (no interim Node/Next dev server) — see Decisions Already Made.
