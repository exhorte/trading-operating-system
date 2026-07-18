# Handoff Log

For concise chronological change tracking, also read `project/changelog.md`.

## 2026-07-18 (2) - Iteration 2 validated bit-identical; candidate frozen; Phase 13 designed

**Iteration 2 closed** (run `bt-mrpq4try-b20fc81b`, verified in the report): the pre-registered invariant held **exactly** — train n=270/+0.23R/+62.04R, validation n=76/+0.21R/+16.08R, bit-for-bit the NY AM buckets of iteration 1. That simultaneously confirms the session filter, the runner's determinism, and the absence of hidden coupling with the removed London trades. Validation timeouts contribute +7.08R of the +16.08R, so the decided-only result stays ≈ +9R — not a timeout artifact. 0 rejections (NY AM is risk-gate-enabled; the strategy filter and risk gate no longer overlap).

**The user's framing is the load-bearing part**: this run is NOT an independent validation. NY AM came out of iteration 1's own segmentation; the run deliberately reproduces that subset. The old train/validation is now **consumed as development data**. Recorded as workflow rule 7: no new filters mined from the consumed dataset, **old OOS never unlocked** (leak-compromised), and the frozen candidate faces exactly one remaining verdict — a virgin holdout plus net-of-costs metrics. No paper trading before both.

**Candidate frozen in code**: `CANDIDATE_CONFIG_2026_07_18` (lib/strategy/config.ts) — spelled out literally, deliberately NOT spread from `DEFAULT_TRIGGER_CONFIG` so default drift can't silently move it; a unit test locks every value; editing it = creating a new candidate.

**Phase 13 designed, awaiting validation** (`phase-13-execution-realism-design.md`), design only — no code:

- Virgin holdout: anterior **2024-06-01 → 2025-06-06** (never imported → provably unconsulted; declaring the boundary leaks nothing); forward holdout accumulates as complement; old OOS retired. Tooling lock applies the leak lessons BEFORE the data exists: default runs clip holdout candles out (exploration impossible by construction); `--verdict-holdout` runs exactly the frozen candidate and rejects every override flag; one read, ever. Regime caveat (2024-25 gold bull favors a bias-following long) recorded a priori with the mitigation: read BUY/SELL separately, trust the forward holdout more.
- Costs: separate post-processing layer (`costs.ts` pure) — outcome simulation untouched so gross numbers stay comparable across all runs; `costR = (spread + 2×slippage + commission/contractSize)/riskDistance`, volume cancels; conservative asymmetries (no favorable slippage on TP); timeout exits pay full round trip. Proposed: spread 0.20 calibrated against stored live ticks (take the WORSE), slippage 0.05/leg, commission per the user's Exness account type. Parameters freeze before the verdict run. Schema += `cost_r`/`net_r_multiple` (additive); report + `/backtests` gross AND net.
- **To fix with the user before implementation**: the pass bar (proposal: net expectancy > 0 at n ≥ 100, neither side catastrophically negative) and the cost parameters. The pass bar must be fixed BEFORE the read or it will be negotiated after it.

Gates: 91 Vitest (frozen-candidate lock test added), tsc exit 0, lint clean. Committed as the Phase 12 closure commit (see changelog). Next session: user validates the Phase 13 design (holdout window, cost params, pass bar) → implement → import anterior history → the single verdict run.

## 2026-07-18 - Iteration 1 committed; /backtests lock; setup metadata; timeouts doc; iteration 2 ready

**Iteration 1 verified and committed (`6203da8`)** after the user's run `bt-mrp973lv-965814cc`: every claimed number checks out against the report. The trigger did exactly what it was built to do — 1–2-bar trades collapse (train 42%→16% of trades, validation 76%→15%), validation cum −23R → −3.67R at n=131 (powered), both-touch 23→0. Verdict (user): audited and promising, **not** promoted to paper (validation still negative, no costs). The one finding passing all four rule-3 criteria is the session split: NY AM +0.23R/+0.21R vs London −0.22R/−0.36R, consistent train/validation with n ≥ 30 everywhere.

Three pre-run fixes (user-specified), all delivered:

1. **`/backtests` OOS leak closed** — the deferred third surface. `BacktestRepository` now recomputes every displayed aggregate in SQL over `split IS NULL OR split <> 'oos'` (LATERAL aggregates + a gaps-and-islands lateral for `maxConsecLosses`; formulas mirror `lib/backtest/metrics.ts` — keep in sync). **Also excludes OOS rows from the trade list**: individual R multiples are summable, so the list is under the same lock as the aggregates. `OosTradeCount` drives a 🔒 note in the workspace. Validated value-for-value against the live DB on both Phase-12 runs (incl. streaks 17/23). Legacy runs (split NULL) count fully — pre-discipline, already read.
2. **Trigger setup metadata** — the user caught that `fvgInside` measures a different notion (entry price inside ANY aligned gap at signal time; the trigger's entry is the confirmation close, usually already outside its own gap — hence the nonsensical 3/496). `evaluateTrigger` now returns `{ signal, setup }` with the exact traded setup (fvgLow/High/Size, fvgAgeBars, shiftAgeBars, retestDepthPercent, atr, stopBuffer); the runner merges these as ADDITIVE feature keys (frozen ADR 0013 set untouched); three new bucketed report dimensions (`setupFvgSize`, `setupFvgAge`, `setupRetestDepth`) render "(missing)" for sampler runs by design.
3. **Timeouts documented** (`backtest_mvp.md`): exit at the last horizon bar's close when neither level is touched within `--max-bars`; excluded from winRate/avgR (decided-only), included in expectancy/cumulative; negative-R timeouts count in loss streaks. Iteration 1 runs 17% timeouts at +0.4R avg — the win rate understates the trigger arm; timeouts are a measurement-horizon artifact, no live equivalent exists, and `--max-bars` must not be tuned against results.

**Iteration 2 designed AND implemented** (`phase-12-iteration-2-design.md`; user's hypothesis, fully constrained): `TriggerConfig.allowedSessions` (null = all, so iteration 1 stays byte-identical), gate first in `evaluateTrigger`, runner `--sessions new_york_am` recorded in the run config. The restriction lives in the STRATEGY layer; the Risk Engine's session gate is untouched (a strategy choosing when to trade is not a risk override). **Pre-registered prediction, stated before the run**: stateless trigger + independent trade simulation ⇒ iteration 2 must be bit-identical to iteration 1's `session=new_york_am` buckets (train n=270/+0.23R, validation n=76/+0.21R). Match = auditable record; deviation = pipeline defect, not a result. The run doubles as an invariant test.

Gates: lint clean, tsc exit 0, **90 Vitest** (+3 session gate, +1 setup metadata), dotnet build 0/0 + 20/20, repository SQL validated live. Next: the user runs iteration 2, then the campaign continues toward a **fresh holdout** (current OOS compromised by the leak). Not committed at time of writing (commit follows this entry).

## 2026-07-17 - Phase 12 Part B iteration 1: entry trigger IMPLEMENTED (+ OOS leak fixed, verified)

Verified the OOS leak fix (gates were pending in the prior entry): **71 → 86 Vitest**, tsc exit 0, lint clean. The de-confounded report `bt-mrowayu5-fdd94b71` confirms the user's read exactly — train +13.1R (buy +26.43 / sell −13.33), validation −23R (buy −22 / sell −1); 1–2-bar losses dominate both splits; inside-FVG coherent but validation n=19. The leaked headline (`+9.1R` over 1,261 incl. OOS) implies **OOS ≈ +19R** — a flattering number precisely of the kind that would tempt shipping. Hence the plan's last step: the current OOS is no longer pristine, a genuinely fresh holdout must be reserved later.

Then implemented iteration 1 (the user's chosen direction — a real entry trigger, not a filter on the sampler):

- **`lib/analysis/atr.ts`** — Wilder ATR, pure, `lib/domain` only. Deliberately a standalone helper: it does NOT touch `MarketContextState` or the score, so the analysis engine and its no-look-ahead invariant are untouched. + 4 tests.
- **`lib/strategy/`** — new pure engine (imports only `lib/domain` + `lib/analysis`). `evaluateTrigger` is a pure `(window, context) → StrategySignal | null`. Setup: directional bias → fresh aligned structure shift → fresh aligned FVG formed after it → **first** retest of the gap → confirmation close → 2R. Stop = beyond the gap's far edge + ATR buffer (floored at ticks). + 11 tests covering each gate, first-retest-only, the three confirmation modes, expiry, neutral, and no-look-ahead.
- **Two code traps that shaped the design** (both real, both in the repo): `fvgId` is a rolling-window index — NOT stable across bars — so the trigger is **stateless by construction** ("first retest" / "one per setup" derived from the window, never tracked); and `MarketContextState` cannot express "first retest" (`activeFairValueGaps` only drops 100%-filled gaps, `filledPercent` runs to the last candle), so the trigger scans the window itself. This is why it takes `(window, context)`, not context alone.
- **Confirmation close fixed a priori to `middle`** (in bias direction AND holds the gap). All three modes are implemented so lenient/strict can be a *future* single-hypothesis iteration; not tuned now.
- **Runner**: `--strategy sampler|trigger`; trigger defaults `--every 1` (a retest lands on any bar); `engine_version` + `config.strategy` record the arm. **The sampler path is byte-for-byte unchanged** — the control arm stays reproducible.
- **Reporter**: `stopDistance` range-buckets (`<3 / 3-5 / 5-7 / 7-10 / 10+`) now that the stop is continuous.

Gates: lint, tsc exit 0, **86 Vitest**. **Behavioral smoke test** (scratchpad, no DB — Docker was down): the real analysis engine + trigger over 2,668 bars of a noisy synthetic walk fired **90 signals (3.4% of bars)**, balanced buy/sell, all with correct 2R geometry and the score passed through untouched. Proves the wiring emits well-formed signals, the first-retest gate holds (not every bar), the setup is reachable (not zero). Synthetic data → indicative of firing rate only, nothing about edge.

**Next (the user's step — needs Docker + DB):** `docker compose up -d`, then `npx tsx scripts/backtest.ts --strategy trigger`, then the report. Compare vs the de-confounded sampler control on train then validation; primary = expectancy R, secondary = the 1–2-bar loss share (what the trigger targets). Ships only if it improves on train AND holds on validation. **Pre-registered**: if validation n < 30 → inconclusive, do NOT loosen the trigger to chase n. OOS stays locked; a fresh holdout comes later. **Still open**: the `/backtests` page leaks OOS-inclusive metrics. Not committed at time of writing.

## 2026-07-17 - Phase 12 Part B: OOS lock leak fixed; iteration 1 designed (entry trigger)

**The user analyzed the de-confounded report and found a leak in the OOS lock.** The report headline (`1,261 trades / +9.1R`) was read straight off the `backtest_runs` row — a whole-period aggregate including the 254 OOS trades — while the OOS split was advertised as locked. Two further surfaces had the same bug: `scripts/backtest.ts` printed whole-run metrics on **every** run with no `--unlock-oos` concept at all (the worse leak — visible before the report is opened), and the `/backtests` page renders the run row permanently (**still open**, needs a product decision; treat as leaking).

Fixed the two scripts; the guard now lives in pure tested code — `reportableTrades(trades, unlockOos)` + `summarize()` in `lib/backtest/segments.ts`, with a regression test asserting the headline never sees OOS R. Lesson (ADR 0013, workflow rule): a lock enforced at the display layer must cover every *derived figure*, not just the obvious section — "hide the section" is not "withhold the information". The revealed numbers cannot be unseen, so iteration 1 was designed without reference to them.

**The user's read of the de-confounded baseline**: it doesn't generalize (train ~neutral/slightly positive, validation negative); no dimension — side, sideVsBias, score, stopDistance, BOS/CHOCH, days, sessions — is stable enough to justify a filter; the robust finding stays the 1–2-bar loss concentration; inside-FVG is coherent across train and validation but validation n is still low. **Decision: iteration 1 = design a real entry trigger, not filter the sampler.**

**Design written** (`phase-12-iteration-1-design.md`, awaiting validation, no strategy code yet): bias → fresh structure shift → fresh FVG created after the displacement → first retest → confirmation close → one signal per setup → setup expiry → stop on structural invalidation + ATR buffer → 2R target unchanged → strict no-look-ahead. Score/sessions/days/Risk Engine/target explicitly untouched.

Two code findings that shaped it:

- **`fvgId` is not stable across bars** — `finalizeGap` emits `fvg-${formedAt}`, an index into the rolling 300-bar window, so ids shift as the window slides and get reused. Any strategy state keyed by `fvgId` would silently corrupt. → the trigger is **stateless by construction**; "first retest" and "one signal per setup" are derived from the window.
- **`MarketContextState` cannot express "first retest"** — `activeFairValueGaps` only drops 100%-filled gaps, and `filledPercent` runs to the window's last candle, so at bar `i` a gap touched at `i` looks identical to one touched at `i-5`. → the trigger takes `(window, context)` and runs its own touch scan.

Also flagged in the design: no ATR exists in the repo (add `lib/analysis/atr.ts`); `--every 8` must become 1 for the trigger (a retest lands on any bar); `--strategy sampler|trigger` keeps the control arm reproducible; `sideVsBias` collapses to `with` only and `stopDistance` becomes continuous (the reporter needs range bucketing). **Main risk, pre-registered**: a strict trigger may leave validation n < 30 → underpowered. Pre-commitment recorded *before* the number exists: do NOT loosen the trigger to chase n (that is overfitting by another route) — extend history or accept "inconclusive".

Open question for validation: the confirmation-close definition (lenient / **middle, proposed** / strict) — it materially changes signal count and must be fixed a priori, not tuned.

**Gates NOT run** for the leak fix: both shell tools were unavailable at time of writing. Unverified — run `npx vitest run`, `npx tsc --noEmit`, `npm run lint` before trusting it. Not committed.

## 2026-07-17 - Phase 12 Part B step 1: the Part A findings were confounded

Audited the Part A findings against the code that produced them before proposing iteration 1 — and the planned iteration was built on an aliased design.

`mockStrategySignal` keyed **three** variety knobs off one counter: `counterBias = seq % 4 === 0`, `stopDistance = 3.5 + (seq % 4) * 1.5`, and a `−3` score penalty applied only to probes. Counter-bias trades were therefore *exactly* the 3.5-stop trades, carrying an artificially docked score — one cohort wearing three labels. The report proves it: `sideVsBias=counter` and `stopDistance=3.5` are numerically identical in every split (n=189 / −0.19R / −36R cum; n=63 / −0.14R / −9R cum).

Why it mattered: running "drop the counter-bias probe" as iteration 1 would have silently deleted the entire tightest-stop cohort too, and the improvement would have been un-attributable — the exact false lesson the split discipline exists to prevent. **Splits catch effects that don't generalize across time; they do not catch a confounded design.** Recorded as ADR 0013 decision 7 and rule 4 of the workflow doc.

Re-graded findings (details in `phase-12-diagnostics.md`): **score 6 positive in both splits** survives (nearly pure with-bias). **1–2-bar losses dominate** survives and is the real signal — the stub fires every 8 bars with *no entry trigger* and a fixed noise-width stop, so it samples arbitrary moments; −0.02R is a random sampler behaving like one. "Counter-bias bleeds" is not attributable; "low scores bleed" is contaminated; **stop distance is no longer a train-only mirage** (3.5 was consistently worst because it was the probe cohort in disguise).

Step 1 shipped (user-validated, an experimental-design fix rather than a strategy hypothesis): `stopDistance` cycles on `seq % 3` (4.0/6.0/8.0) while `counterBias` stays on `seq % 4` — coprime, so all 12 (side, stop) combinations occur per 12-signal period; `score` is passed through undoctored; `segments.ts` reports the measured stop distance instead of snapping to the old hardcoded lattice. Gates: lint clean, `tsc --noEmit` exit 0, 69 Vitest. No tests covered `mockStrategySignal`; its three consumers (mock-client, signalr-client, backtest runner) are unchanged.

Next: **Docker Desktop was down**, so the re-run is the user's step — `docker compose up -d`, then `npx tsx scripts/backtest.ts --symbol XAUUSDm --timeframe M15` and `npx tsx scripts/backtest-report.ts <runId>`. The new run is deliberately **not** bit-comparable to `bt-mrkz8r44-d57578d8`; keep the old one for the record. Then iteration 1 — settle first whether to filter the trigger-less stub (min-score threshold) or give it a real entry trigger (fresh structure shift + PD-array touch, ATR-derived stop), which is what the 1–2-bar-loss finding actually points at. Not yet committed at time of writing.

## 2026-07-14 - Phase 12 Part A: Diagnostics tooling + first findings

Built the diagnostics slice per the user's spec (design validated: 60/20/20 chronological splits; console+markdown report; OOS locked by tooling — `--unlock-oos` to be used once, at the end). Runner v2 captures frozen features per trade (ADR 0013 key set) and all rejections with reasons; `segments.ts` (pure, tested) + `backtest-report.ts` render 15 dimensions × split, worst buckets first, `⚠ low n` under 30 trades.

Enriched baseline `bt-mrkz8r44-d57578d8` reproduced Phase 11 **bit-identically** (32.31% / −0.02R / −21.55R) — the pipeline is deterministic. Splits: train ≤ 2026-02-05, validation ≤ 2026-04-25, oos after.

**Findings that survive train AND validation** (the only kind we act on):

- Counter-bias probes bleed: −0.19R (n=189) / −0.14R (n=63). Mechanically explainable — the stub injects 1-in-4 deliberately.
- Score is directionally informative: score 3 bleeds in both (−0.23R/−0.49R); score 6 is the only bucket positive in both.
- Structural (not a filter): 1–2-bar losses dominate (−0.34R n=316 / −0.23R n=188) — entries die immediately; stop placement/entry timing is the weak joint.

**Train-only mirages killed by validation** — side, structure kind (BOS>CHOCH reversed), stop distance (6.5 best→worst), session edge, bias direction. Without the split these would have shipped as "improvements"; the discipline the user demanded proved itself on day one.

Rejections: 1,948, 100% session filter (Asia/NY-PM/off-session) — gates behaved exactly as configured.

Next (Part B, after joint review): iteration 1 candidates — remove the stub's counter-bias probe; add a minimum-score threshold in the STRATEGY layer (the risk engine stays a risk engine). One hypothesis per iteration, `--to <trainEnd>` runs, validation must confirm. Not yet committed at time of writing.

## 2026-07-14 - Phase 11 Closed: the baseline is honestly negative

The user ran the first real backtest (`bt-mrkx74n5-500ff1f8`, XAUUSDm M15, 13 months, 25,999 candles): 3,209 signals, 1,261 approved trades, **win rate 32.31%, expectancy −0.02R, cumulative −21.55R, max 21 consecutive losses**. With 2R targets the theoretical break-even is ≈33.3% — the stub strategy is statistically near-random, as one should expect from a stub. **Conclusion (user): engine v0.1 has no edge; no paper trading in this state.**

This is the platform working as designed: the manifesto's "backtest before confidence" gate produced a number instead of a feeling, and the number said no. The pipeline itself (import → runner → persisted runs → Backtests page) is validated end-to-end.

Key handoff for Phase 12 (Backtest Diagnostics & Strategy Refinement, user-specified):

- Diagnose BEFORE changing rules: segmented analyses by side, session, day/month, bias, BOS/CHOCH, FVG/OB, score, liquidity type, planned RR, duration, timeout, both-touch, and risk gates (including WHY 1,948 signals were rejected).
- **Important data gap**: `backtest_trades` does not yet store the signal's market-context features (bias, structure kind, PD arrays, liquidity, price location…) — the runner computes them but drops them. Phase 12 must add a `features` capture and re-run the baseline (idempotent; old run kept for comparison).
- Anti-overfitting discipline is mandatory: chronological train/validation/out-of-sample split; iterate on train, confirm on validation, touch OOS once.
- Explicitly deferred until the raw R distribution improves: cost modeling, paper trading.

Also this session: `context/project/session-history.md` added; full history (17 commits) pushed to `https://github.com/exhorte/trading-operating-system.git`.

## 2026-07-12 - Phase 11 Implementation (Backtesting MVP)

Implemented after design validation (Backtesting MVP scope; ~1 year M15). This is the manifesto's "backtest before confidence" gate, now measurable because history persists (Phase 10).

The whole point paid off: `scripts/backtest.ts` (Node, run via `tsx`) imports the SAME pure engines the platform runs live (`lib/analysis` ICT/SMC, `lib/risk` FTMO gates + sizing, the strategy stub) and replays them walk-forward over stored candles — no engine port, no reimplementation. The no-look-ahead invariant (tested since Phase 04) is what makes historical replay legitimate; same 300-bar rolling window as the live clients.

Built: `import_history.py` (read-only JSONL export, zero trade imports) + `scripts/import-candles.ts` (idempotent bulk upsert; dev deps tsx/pg/@types/pg); `lib/backtest/{outcome,metrics}.ts` pure + 9 tests (binary SL/TP, conservative both-touch = loss + flag, timeouts; win rate/avg R decided, expectancy R over all, max consec losses, cumulative R, both-touch count); `backtest_runs`/`backtest_trades` tables (idempotent schema); `BacktestRepository` + `GET /api/backtests(/{id})` (audit-endpoint error discipline; timestamptz→DateTime lesson applied); real Backtests page under a permanent hypothesis banner.

Honesty (surfaced everywhere): engine v0.1, no spread/slippage/costs, binary exits, no account-level simulation — results grade SIGNAL QUALITY (R distribution), never account performance.

Gates run before commit (see below). Runbook: `context/backtesting/backtest_mvp.md`. Next: the user imports history and runs the first backtest; the resulting R distribution decides whether to iterate the engine (backtester as feedback loop) or move toward cost-aware simulation + paper trading. Not yet committed at time of writing.

## 2026-07-12 - Phase 10 Closed (validated live)

The user's live run confirmed persistence end-to-end: `/health` db ok with thousands of envelopes persisted and 0 dropped; direct SQL over the audit tables; `/api/audit/recent` 200 after the reader fix. Root cause of the 503 the user caught: Npgsql materializes `timestamptz` as `DateTime` and Dapper's constructor mapping threw `InvalidCastException` against the record's `DateTimeOffset` parameter — hidden by a bare catch. Fixed (`AuditEntry.SentAt` = UTC `DateTime`), the endpoint now logs and surfaces the real exception, and `AuditRepositoryIntegrationTests` guards the read path against the live DB (early return when unreachable; xUnit v2 has no runtime skip). Lesson reinforced twice this phase: never swallow persistence errors silently.

Committed `bc48110` + this closure. Next: Phase 11 in phase-start — consume the data (backtesting MVP / replay / DB-backed P&L) or open the paper-trading track (precondition met).

## 2026-07-12 - Phase 10 Implementation (Persistence)

Implemented after design validation (Dapper + versioned schema.sql; signals/decisions routed through the hub; full slice scope). Key structural fix: signals/decisions were browser-local (Phase 09 transitional loop) — `CockpitHub.PublishEvent` (strict whitelist: `strategy.signal.created`, `risk.decision.made`; 64KB cap) now persists and rebroadcasts them, making the hub the source of truth and all tabs consistent.

Built: root `docker-compose.yml` (TimescaleDB pg17, **host port 5433** — 5432 collided with a locally installed Postgres, found via `28P01` auth failure against the wrong server; also: Docker Desktop had to be started), `TradingOs.Persistence` (embedded idempotent schema — 8 tables incl. 2 hypertables and the `envelopes` JSONB audit; pure `PersistenceMapper` + 5 xUnit tests; `PersistenceWriter` bounded-channel drain, fire-and-forget, drop-with-counters, `LastError` surfaced after an initial silent-catch made diagnosis impossible — lesson: never swallow persistence errors silently), Host wiring (`/health` + `/api/audit/recent`), client `publish()` with local-apply fallback.

Gates: dotnet build 0 errors + 19/19 xUnit, lint clean, source tsc exit 0, 56 Vitest. The final DB smoke test on 5433 + the live run are pending (shell tool intermittently unavailable at time of writing; docs written meanwhile). Runbook: `context/backend/persistence.md`.

Next: user's live run (compose up + 3 terminals; verify db: ok + audit rows), close Phase 10, then Phase 11 (consume the data: replay/P&L/backtesting) or the paper-trading track.

## 2026-07-11 - Phase 09 Closed (validated live; idempotency exercised for real)

The user's 3-terminal run validated the whole loop: signals both sides (counter-bias sell 4/10 included) → risk-sized decisions with varied volumes (0.12–0.28 lot tracking stop distance) → commands → ACCEPTED acks → `simulated` reports ("observe mode, no broker order") in the cockpit feed.

Bonus finding: the run exercised **real idempotency** — the cockpit was restarted without restarting the observer, the counter-based ids replayed (`cmd-sig-117`…), and the agent's module-level dedup set (which deliberately survives reconnects) answered DUPLICATE and refused to re-simulate. No double fill: the specified behavior, proven in real conditions.

Two defects surfaced and fixed at closure: (1) ids were not session-unique (counter reset per client instance → guaranteed collisions across restarts/tabs against a persistent dedup set) → `sig-{runId}-{seq}` with a per-session base36 prefix; the mock keeps its old format. (2) DUPLICATE/ACCEPTED ack reasons were overwriting the risk-decision text on signal cards → confirmations now keep the decision text; only failure reasons replace it. Gates re-verified (lint, 56 Vitest).

Next: Phase 10 - Persistence (PostgreSQL/Timescale) in phase-start — the user's precondition before any paper trading.

## 2026-07-11 - Phase 09 Implementation (Execution Bridge, observe/SIMULATED)

Implemented against the user's explicit 10-point spec (design + 3 choices validated first: transitional in-browser decision loop; `simulated` status + `execution.order.simulated` + canonical ack payload; 5s timeout with one same-id retry).

The loop: approved `RiskDecision` → `buildPlaceOrderCommand` (`lib/execution/command-builder.ts` — the ONLY way a command exists; volume = approvedVolume; rejected/unsized/mismatched → null) → `SignalRRealtimeClient` invokes `CockpitHub.SubmitCommand` → hub broadcasts the command envelope to all dashboards, guards agent mode (non-observe/absent/unknown → synthesized rejected ack, never forwarded) → `FlattenPlaceOrder` to lean `execution.order` → first outbound frame over the existing observer WS → observer (v0.2.0, producer‖consumer via `asyncio.TaskGroup`) validates (required fields, MARKET only, served symbol, volume bounds from broker info, mandatory SL), checks expiry, dedupes by commandId (module-level set, survives reconnects) → `execution.ack` then `execution.report SIMULATED` with live tick price → gateway maps ack → canonical `CommandAckPayload` events and SIMULATED → `execution.order.simulated` → store drives `commands` map + signal statuses (commanded→acknowledged→reported).

Key safety layering (four independent barriers): risk-gated builder · hub observe guard · agent `EXECUTION_MODE="observe"` constant with ZERO trade imports (a "fill" is a JSON reply) · distinct `simulated` status never rendered as a fill. Rejected/expired/duplicate never produce a report (tested TS-side; enforced agent-side).

Contract work: domain `ExecutionReportStatus` += `simulated`; EventType += `execution.order.simulated`; **Phase 01/02 ack shortcut resolved** (`execution.command.acknowledged|rejected` now carry `CommandAckPayload`). C# `Execution.cs` mirrors 1:1; 14/14 xUnit (one stale Phase 08 parser assertion updated — execution.ack/report joined the parser). Store: `ExecutionCommandView`, `markCommandRetried/Failed`, idempotent place_order re-registration (retry never downgrades lifecycle).

Gates: lint clean, source `tsc` exit 0, 56 Vitest (3 builder + 6 store new), dotnet build 0/0, `py_compile` OK, trade-call grep clean (only a docstring mention).

Next: user's live 3-terminal run (expect: signals every ~30s in backend mode → sized decisions → ACCEPTED acks → SIMULATED reports in the feed; observer console logs dedup/rejections). Then close and start Phase 10 Persistence (PostgreSQL/Timescale) — **before any paper trading** (user decision). Not yet committed at time of writing.

## 2026-07-11 - Phase 08 Closed; LiveRealtimeClient Deleted

Phase 08 closed after the user's live 3-terminal validation: `/health` returned ok, the cockpit showed DEMO + connected on the real Exness demo (436634705, equity $9,902.51) with market context computed from real candles and honest observe-mode gates — translation running server-side in .NET.

Cleanup at closure: deleted `lib/realtime/live-client.ts` (the ADR 0007 browser-translation shortcut, now superseded); provider offers `mock` (default) and `backend` only; `.env.example` simplified. **Kept** `lib/realtime/mt5-translate.ts` + its tests as the canonical TS reference that `Mt5WireTranslator.cs` mirrors 1:1 — change both together.

Next phase-start decision: Phase 09 Execution Bridge in observe/SIMULATED mode (full command loop through the gateway: ExecutionCommand → lean execution.order → SIMULATED ack/report; exercises idempotency/expiry at zero broker risk) or persistence (PostgreSQL/Timescale for candles/decisions/audit/replay).

## 2026-07-10 - Phase 08 Implementation (ASP.NET Core Backend Bootstrap)

Designed and implemented after user validation (backend in this repo under `backend/`; minimal observe-only stateless slice). The production transport now exists: MT5 → Python observer → **.NET gateway (server-side translation)** → SignalR → cockpit.

Built:

- `backend/TradingOs.slnx` (.NET 10, note: new `.slnx` solution format). Projects: `TradingOs.Contracts` (C# mirrors — `Envelope<T>`, lean `Mt5*Message` records + `Mt5WireParser` type-discriminator dispatch, camelCase read models so the TS store consumes them unchanged), `TradingOs.Gateway` (`Mt5WireTranslator` = C# port of `mt5-translate.ts`, `GatewayState` snapshot store, `Mt5ObserverClient` — WS client dialing `ws://localhost:8765`, read-only, auto-reconnect), `TradingOs.Host` (SignalR `CockpitHub` at `/hub/cockpit` with `GetSnapshot` + `event` envelope broadcasts, `/health`, CORS for `localhost:3000`, `GatewayBridgeService`; listens on `http://localhost:5080`).
- `tests/TradingOs.Gateway.Tests`: 7 xUnit tests mirroring `mt5-translate.test.ts` 1:1 — the two translators must stay in sync until the TS one is deleted.
- Frontend: `SignalRRealtimeClient` (snapshot hydrate + event stream, heartbeat watchdog, initial-connect retry; TS engines still run client-side: ICT/SMC on relayed candles, observe-mode risk with session baseline). Provider source `backend` (`NEXT_PUBLIC_BACKEND_HUB_URL`); store gained `agent.snapshot.positions`; `@microsoft/signalr` added — first frontend runtime dependency.
- ADR 0009, `context/backend/backend_bootstrap.md` (3-terminal runbook), phase-08 files. `.gitignore`: `backend/**/bin|obj`.

Verified here: `dotnet build` 0/0, `dotnet test` 7/7, host smoke test (`/health` 200, SignalR negotiate 200), frontend lint clean / source `tsc` exit 0 / 47 Vitest tests. **The live 3-terminal run is the user's step.**

Key handoff:

- Connection direction is prototype-era: the gateway DIALS the observer (which is a WS server). The definitive MQL5 agent + sidecar will dial the gateway (ADR 0005); only `Mt5ObserverClient` changes then.
- `LiveRealtimeClient` (browser translation, ADR 0007) is superseded — keep as fallback until the backend path is validated live, then delete it (and its translator? no: `mt5-translate.ts` types/tests stay as the reference the C# mirrors).
- Engines remain TS client-side in this slice; porting to C# is a later decision.
- Not yet committed at time of writing.

## 2026-07-10 - Phases 06 + 07 Closed; Mock Variety; Next = Backend

Closed Phase 06 (Risk & Prop Firm Mode) and Phase 07 (Signal → Risk Review + `/signals` audit workspace) after the user reviewed both in the running cockpit — the risk panel live against their real Exness demo, and `/signals` showing real decisions (volume, reason, gates) and fills.

Also shipped "mock variety" (`59fa86e`): `mockRiskContext(scenario)` rotates normal / wide_spread / closed_session and the mock client publishes the same `RiskState` to the panel that the review uses, so rejections match the cockpit; `mockStrategySignal` emits counter-bias probes and cycling stop distances (varied volumes). One rotation yields: sell 2.89 lot, buy 2.02, spread-gate rejection, buy 1.26, session-filter rejection.

Operational lesson recorded: never run `next build` while the user's dev server is running — both write `.next/` and the dev route manifest gets corrupted (caused a transient 404 on `/signals`, fixed by restarting dev). Verify with lint + isolated `tsc` (temp tsconfig excluding `.next`) + vitest instead.

Next: Phase 08 - ASP.NET Core Backend Bootstrap (phase-start; design then user validation). Roadmap renumbered: Execution Bridge → 09, Backtesting → 10.

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
