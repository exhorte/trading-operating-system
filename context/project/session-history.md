# Session History

A durable, human-readable log of the working sessions in which the Trading
Operating System went from "Phases 01–03 delivered, awaiting review" to a
persisted, backtestable, diagnostics-driven end-to-end trading loop with a
frozen strategy candidate awaiting its virgin-holdout verdict (Phases 04–13).
It complements `changelog.md` (chronological facts), `handoff.md`
(per-session narrative) and the per-phase files under `phases/`.

> This file records what happened and why. For the authoritative current state,
> always read `project_state.md` first.

## Arc at a glance

| Phase | What shipped | Commit | Live-validated |
| --- | --- | --- | --- |
| 01–03 | Reviewed and closed together (cockpit shell, domain model, MT5 wire spec) | `afa5295` | cockpit walkthrough |
| 04 | ICT/SMC analysis engine MVP (`lib/analysis`, Vitest introduced) | `298480a` | via mock + Phase 05 |
| 05 | Live observe prototype: real Exness demo → cockpit (browser translation) | `4f56064` | ✅ real demo |
| 04+05 | Closed | `c4464f5` | — |
| 06 | Risk & Prop Firm engine (`lib/risk`, FTMO gates) | `6f1a0c9` | ✅ live risk panel |
| 07 | Signal → Risk Review wired with real `RiskDecision` | `3f4208c` | ✅ |
| 07+ | Full `/signals` audit workspace | `d455a72` | ✅ |
| 07+ | Mock variety (rotating scenarios, real rejections) | `59fa86e` | ✅ |
| 06+07 | Closed | `a2fd0e6` | — |
| 08 | ASP.NET Core backend: gateway + SignalR hub (server-side translation) | `0977175` | ✅ real demo via .NET |
| 08 | Closed; deleted superseded `LiveRealtimeClient` | `2f0bd33` | — |
| 09 | Execution bridge, observe/SIMULATED (zero-risk command loop) | `57e96b1` | ✅ + real DUPLICATE dedup |
| 09 | Closed; session-unique ids | `c16c033` | — |
| 10 | Persistence (TimescaleDB, Dapper, hub-published signals) | `bc48110` | ✅ thousands persisted |
| 10 | Closed; `/api/audit/recent` 200 after reader fix | `323d6e7` | ✅ |
| 11 | Backtesting MVP (reuse live engines over stored candles) | `d7d9106` | ✅ first real run |
| 11 | Closed: baseline honestly negative (−0.02R, no edge) | `1112e39` | ✅ user's run |
| 12A | Diagnostics: features, 60/20/20 splits, locked OOS, 15-dim report | `b81c9ca` | ✅ bit-identical re-run |
| 12B | De-confound stub, OOS lock hardening, iteration 1 entry trigger | `6203da8` | ✅ run `bt-mrp973lv` |
| 12B | `/backtests` OOS lock, setup metadata, iteration 2 (NY AM) | `f8f4d9f` | ✅ run `bt-mrpq4try` |
| 12 | Closed: invariant test bit-identical, candidate frozen | `9dbfb62` | ✅ |
| 13 | Virgin-holdout lock, frozen cost profile, verdict machinery | `a537417` | guards verified |
| 13 | Pre-verdict tooling: spread calibration, swap inspection, exact-bounds import | `963d1d0` | guards verified |
| 13 | Swap freeze (XAUUSDm Standard, POINTS → −48.28/0.00 USD/lot/night, UTC+0 verified) | _(uncommitted)_ | MT5 spec confirmed |
| 13 | Virgin holdout imported (23,947 M15, 2024-06-02→2025-06-06, bounds verified) | _(uncommitted)_ | SQL verified |

Model note: the sessions ran mostly on Claude Fable 5, with a few segments on
Claude Opus 4.8.

## Chronological narrative

### Start — `--continue`
Resumed at the end of Phase 03. The user chose to **review and close Phases
01–03 together** and to **defer the WebSocket Gateway until the ASP.NET Core
backend exists**. Verified gates (lint, tsc, build 13 routes), confirmed all
deliverable artifacts, closed the three phases (`afa5295`).

### Phase 04 — ICT/SMC Engine MVP
Chosen over the (blocked) realtime prototype; built in **TypeScript in this
repo** against `lib/domain`. Pure detectors — swings → structure (BOS/CHOCH) →
liquidity (equal highs/lows, PDH/PDL, swept) → PD arrays (FVG, order blocks) →
session → bias → weighted scoring → `MarketContextState`. Introduced **Vitest**
(first new dependency since Phase 01, mandated by the testing strategy). A
`no-look-ahead` invariant was made explicit and asserted in tests. The mock
cockpit began rendering **computed** market context. `298480a`.

### Phase 05 — Live Observe Prototype
The user asked to test against their real Exness demo; established the hard rule
**never share credentials** (a local reader attaches to the already-logged-in
terminal). Built a **read-only Python `MetaTrader5` producer** streaming the
lean `mt5-wire` protocol, and a browser `LiveRealtimeClient` translating it into
the store and running the Phase 04 engine on real M15 candles. First real
end-to-end proof: **badge DEMO + connected, real balance/positions/ticks**.
Fixed the KPI strip to degrade gracefully when `risk` is null. `4f56064`, closed
with Phase 04 in `c4464f5`.

### Phase 06 — Risk & Prop Firm Mode
Pure TS risk engine (`lib/risk`): one gate per FTMO guard (daily loss, max
drawdown, open risk, max trades, consecutive losses, spread, session; news
stub), `evaluateRiskState` → normal/warning/locked, `evaluateSignalRisk` →
`RiskDecision` (built + tested, not yet wired). Honesty: trade-history counts
are `number | null` → "n/a" in observe mode; positions without a stop are
excluded from open-risk (a real edge case seen on the live demo). Filled the
last empty panel, live. `6f1a0c9`.

### Phase 07 — Signal → Risk Review
Replaced the mock's faked `score >= 7` approvals with **real `RiskDecision`s**
from `evaluateSignalRisk`. New audit-grade `risk.decision.made` contract. The
mock became a mini strategy emitting domain signals from the computed context.
`3f4208c`. Then the full **`/signals` audit workspace** (lifecycle, levels,
decision + gates, fills) `d455a72`, and **mock variety** (rotating
spread/session scenarios → real rejections, varied sizes/sides) `59fa86e`.
Closed with Phase 06 in `a2fd0e6`.

### Phase 08 — ASP.NET Core Backend Bootstrap
The user chose the backend as the next infrastructure step. Stood up
`backend/TradingOs.slnx` (.NET 10): Contracts (C# mirrors of Envelope, lean
wire, read models), Gateway (`Mt5WireTranslator` = C# port of `mt5-translate.ts`
with mirrored xUnit tests; observer WS client), Host (SignalR `CockpitHub`,
`/health`, CORS). Frontend gained `SignalRRealtimeClient` behind the same seam
(`@microsoft/signalr`, first runtime dep). Translation now happens
**server-side in .NET**. Validated live. `0977175`; closed + deleted the
superseded browser `LiveRealtimeClient` in `2f0bd33`.

### Phase 09 — Execution Bridge (observe/SIMULATED)
Per the user's detailed 10-point spec: approved decision → `buildPlaceOrderCommand`
(volume = approvedVolume) → hub `SubmitCommand` (observe-mode guard) → lean
`execution.order` → observer validation/dedup/ack → `execution.report SIMULATED`
→ canonical `CommandAckPayload` + `execution.order.simulated`. Four independent
safety barriers; **no trade function imported anywhere** — a "fill" is a JSON
reply. Store lifecycle + 5s ack timeout → one same-id retry → failed. Validated
live, and the run **exercised real idempotency by accident** (a cockpit restart
replayed ids → DUPLICATE acks, no double fill), which surfaced two fixes:
session-unique ids and confirmations not overwriting the decision text.
`57e96b1`, closed `c16c033`.

### Phase 10 — Persistence
The user's precondition before any paper trading. TimescaleDB via docker-compose
(**host port 5433** — 5432 collided with a locally installed Postgres,
diagnosed live via a `28P01` auth error against the wrong server). Dapper +
idempotent `schema.sql` (8 tables incl. hypertables + JSONB `envelopes` audit),
a **never-blocking** bounded-channel `PersistenceWriter` (drop-with-counters),
hub `PublishEvent` making the hub the source of truth for signals (multi-tab
consistent), `/api/audit/recent`. `bc48110`. The user caught a `503` on the read
endpoint → root cause **Npgsql timestamptz materializes as `DateTime`** while
the record wanted `DateTimeOffset`, hidden by a bare catch; fixed + logged +
integration-tested. Validated live (thousands persisted, 0 dropped). Closed
`323d6e7`.

### Phase 11 — Backtesting MVP
The manifesto's "backtest before confidence" gate, now measurable. A Node/`tsx`
runner **reuses the exact same pure engines** the platform runs live, walk-forward
over stored candles; the no-look-ahead invariant is what makes that legitimate.
History import (read-only Python export → idempotent bulk upsert), pure tested
`lib/backtest/{outcome,metrics}` (conservative both-touch rule, timeouts),
`backtest_runs`/`backtest_trades` tables, `GET /api/backtests`, and a real
Backtests page under a permanent **hypothesis banner** (engine v0.1, no costs —
grades signal quality, never account performance). `d7d9106`. The user's first
real run (25,999 M15 candles, 3,209 signals, 1,261 trades) returned the honest
answer: **win 32.31%, expectancy −0.02R — engine v0.1 has no edge**;
near-random for a stub, no paper trading in that state. The negative number WAS
the deliverable: the gate measured instead of hoping. Closed `1112e39`.

### Phase 12 — Backtest Diagnostics & Strategy Refinement
Part A (`b81c9ca`): frozen per-trade **feature capture**, rejection recording,
chronological **60/20/20 train/validation/OOS splits**, and a 15-dimension
segmented report with **OOS locked by tooling**. The enriched baseline
reproduced Phase 11 **bit-identically** — the pipeline is deterministic.

Part B opened with a hard lesson: the first findings were read off a
**confounded stub** — counter-bias, stop distance and a score penalty all keyed
off one counter, so three "effects" were one aliased cohort. Splits catch
effects that don't generalize across time; they do NOT catch an aliased
design. De-confounded (coprime knobs, undoctored score), and the user then
caught an **OOS lock leak**: whole-period aggregates (report headline, runner
console, later the `/backtests` page) silently included the locked OOS trades.
The guard moved into pure tested code (`reportableTrades`/`summarize`), then
into SQL for the page — "hide the section" is not "withhold the information".

**Iteration 1** (`6203da8`): a real entry trigger (`lib/strategy`,
`ict-fvg-retest-v1`) — bias → fresh aligned structure shift → fresh FVG formed
after it → **first retest** → middle confirmation close → structural stop +
0.5 Wilder-ATR buffer (new `lib/analysis/atr.ts`) → 2R unchanged. Stateless by
construction (`fvgId` is a rolling-window index — any keyed state would
corrupt). Run `bt-mrp973lv`: **1–2-bar losses collapse** (42%→16% of trades in
train, 76%→15% in validation), validation −23R → −3.67R at n=131 — behavioral
target hit, still negative, **not promoted**. Robust finding: the session
split (NY AM +0.23R/+0.21R vs London −0.22R/−0.36R).

**Iteration 2** (`f8f4d9f`): trigger restricted to NY AM, nothing else moved,
with a **pre-registered prediction**: stateless trigger + independent trades ⇒
the result must be bit-identical to iteration 1's NY-AM buckets. Run
`bt-mrpq4try`: it was, exactly (train n=270/+0.23R/+62.04R, validation
n=76/+0.21R/+16.08R) — validating the filter, the determinism, and the absence
of hidden coupling in one shot. But NY AM was selected post-hoc from the same
report, so the user ruled: **the dev dataset is consumed**, no further filter
mining, old OOS never unlocked (leak-compromised), and the candidate —
**frozen as `CANDIDATE_CONFIG_2026_07_18`**, test-locked — faces exactly one
remaining verdict. Closed `9dbfb62`.

### Phase 13 — Execution Realism & Virgin Holdout (in progress)
Design validated by the user with exact bounds, then implemented (`a537417`):
**virgin holdout** 2024-06-01T00:00Z → 2025-06-06T13:30Z *exclusive* (never
imported — provably unconsulted; ordinary runs CLIP its candles by
construction), **frozen conservative cost profile** (spread 0.26 persisted
literally, slippage 0.05/leg, commission 0, `swap: null`; stress 0.30/0.10
informative-only), and the **single-read verdict machinery**: pre-registered
PASS/INCONCLUSIVE/FAIL bar (FAIL-first precedence, seeded 10k bootstrap →
bit-reproducible), `--verdict-holdout` mode rejecting every override, dirty-tree
refusal, sha256 hashes (commit/dataset/candidate/costs), single read enforced
by a DB primary key, audited attempts, and a **swap invariant** that refuses
the verdict with zero metrics computed if any trade crosses a 21:00/22:00 UTC
rollover while swap is unmodeled — the holdout stays virgin on refusal.

Second review (`963d1d0`): bounds and bar validated **definitively**; instead
of burning an attempt on the swap refusal, pre-verdict tooling: NY AM spread
calibration from stored ticks (coverage-guarded — refuses under 3 sessions),
a read-only MT5 swap/spec inspector with **mode-aware normalization** (raw
swap values are never assumed USD/lot/night), and `--from/--to` exact-UTC
import bounds so the holdout dataset hash is reproducible bit-for-bit.
Remaining: tick collection → re-freeze costs → swap freeze → import → final
pre-read summary → user approval → **the one read**.

### 2026-07-27 — Swap freeze + holdout import (pre-verdict tooling executed)

Two of the three pre-verdict steps were executed today:

**Swap inspection & freeze.** `inspect_symbol.py --symbol XAUUSDm` captured the
broker's swap specification from the logged-in MT5 terminal (Exness-MT5Trial9,
Standard account — confirmed NOT swap-free). Key findings: swap_mode = `POINTS`
(1), raw swap_long = −482.8, raw swap_short = 0.0. Normalized via the
deterministic POINTS formula (`tick_value 0.1 × point 0.001 / tick_size 0.001`
→ 0.10 USD per point): **long −48.28 USD/lot/night, short 0.00 USD/lot/night**,
confidence `computed` (no manual FX conversion needed — account is USD). Triple
swap on Wednesday (MQL5 day 3). Server time verified by the user: Exness server
= UTC+0 (2h behind local CEST), so `rolloverHourUtc = 0` (server midnight =
00:00 UTC). The user confirmed both the swap values displayed in MT5
Specification and the Standard account type. The `SwapSpec` was frozen into both
`FROZEN_COST_PROFILE_2026_07_18` and `STRESS_COST_PROFILE` in
`lib/backtest/costs.ts`, with full provenance chaining to the capture JSON.

**Holdout import.** `import_history.py` exported 23,947 M15 candles for XAUUSDm
from MT5 (2024-06-01T00:00Z → 2025-06-06T13:30Z), then `import-candles.ts`
upserted them into TimescaleDB. SQL verification confirmed the bounds:
min = 2024-06-02 22:00 UTC (Monday open, ≥ 2024-06-01), max = 2025-06-06
13:15 UTC (< 2025-06-06T13:30Z). No development candles in the holdout range.

**Spread calibration status.** `calibrate-spread.ts` still refuses: 1/3 minimum
NY AM sessions (Mon 2026-07-27; n=14,044, session started late due to harness
background-task kills, processes later detached with `dangerouslyDisableSandbox`).
At least 2 more NY AM sessions (12:00–16:00 UTC) are needed before the spread
can be re-frozen and the verdict can run.

**SwapSpec sufficiency.** The swap specification is fully determined — no manual
confirmation outstanding. POINTS mode normalization is formulaic, both long and
short are `confidence: computed`, the account is USD, server timezone is verified,
and the values match the MT5 Specification display.

### 2026-07-27 — NY AM tick collection session #1

First of the required ≥3 NY AM sessions for spread re-calibration (Phase 13
pre-verdict). The session ran 12:00–16:00 UTC on the live Exness demo account
(436634705, XAUUSDm, Standard).

**Infrastructure:** TimescaleDB (Docker, `tradingos-timescaledb`), ASP.NET Core
backend (`TradingOs.Host`, port 5080), Python observer (`mt5_observer.py`,
port 8765). The backend's `PersistenceWriter` inserts every tick into the
`ticks` hypertable with no blocking, no drops.

**Session result:** 14,044 ticks recorded (12:00:00.141 → 15:59:59.154 UTC),
~0.97 ticks/sec steady rate. 0 drops, db ok throughout.

**Harness lesson:** Background tasks (`run_in_background`) are killed after ≤10 min
by the harness. The solution: `dangerouslyDisableSandbox: true` + bash `&` operator
detaches the process from the harness; processes then survive indefinitely.
The backend and observer were still running 30 min after the session closed.

**Cron scheduling:** One-shot reminders set for Tue–Fri (28–31 July) at 13:57
local (11:57 UTC, 3 min before session start). An emergency restart cron
(`*/8 14-17`) was active during today's session but is now cancelled (processes
are stable when detached).

**Next:** Collect ≥2 more NY AM sessions (Tue–Fri target). The backend and
observer processes may be left running across days, or restarted per session.
After ≥3 sessions total: `npx tsx scripts/calibrate-spread.ts` → freeze final
spread → pre-read summary → user approval → the single `--verdict-holdout` read.

### 2026-07-28 — NY AM tick collection session #2 (closed)

Second NY AM session. Infrastructure was down at 10:30 UTC (Docker container
stopped, backend/observer not running) — relaunched at 10:33 UTC. Session
started at 12:00 UTC with ticks flowing normally.

**Observer stall at 14:03 UTC:** Tick flow stopped abruptly — the Python process
was still alive (PID 60720) but `symbol_info_tick` ceased returning data. Likely
cause: MT5 terminal disconnection or idle timeout. The backend stayed healthy
and the WebSocket remained connected. Observer killed and restarted at 14:04
UTC; ticks resumed immediately. ~1 minute of data lost — negligible impact on
the session total.

**Session result:** 14,146 ticks recorded (12:00:00.774 → 15:59:59.762 UTC),
virtually identical to Monday's 14,044. 0 drops, db ok throughout. The observer
stall did not materially affect the sample.

**Crons scheduled:** Bilan final 16:05 UTC, mercredi 29 juillet 11:57 UTC.

**Next:** Session mercredi 29 juillet → si OK, ≥3 sessions → `calibrate-spread.ts`.

## Cross-cutting decisions
- **Engine-first, backend-later**: pure domain engines in TS now, ported/mirrored
  to .NET when the backend arrived (ADR 0004/0006/0008/0009).
- **Two transport worlds** (ADR 0005): lean WSS+JSON at the MT5 edge; SignalR
  dashboard-side; the gateway translates. Browser translation (ADR 0007) was an
  explicit throwaway, superseded by the .NET gateway (ADR 0009).
- **Observe-only, layered safety** (ADR 0010): no order path can reach a broker;
  a `simulated` status that is never a fill.
- **Persistence before paper trading** (ADR 0011); **backtest before confidence**
  (ADR 0012).
- Mono-repo resolved: backend lives under `backend/` in this repo.

## Recurring lessons (worth remembering)
- **Never run `next build` while the user's `next dev` is running** — both write
  `.next/` and the dev route manifest corrupts (caused a transient `/signals`
  404). Verify with lint + an isolated `tsc` (temp tsconfig excluding `.next`) +
  Vitest instead.
- **Never swallow persistence/DB errors silently** — a bare catch hid both a
  writer failure and the audit-endpoint `503`. Always log + surface the real
  exception.
- **Npgsql `timestamptz` → `DateTime`**, not `DateTimeOffset`, for Dapper
  constructor mapping.
- Browser extensions (ColorZilla, Youdao, Mate Translate) inject attributes/
  elements pre-hydration → benign hydration warnings; `suppressHydrationWarning`
  on `<html>`/`<body>` covers attributes; injected elements are auto-recovered.
- Docker host port **5433** for TimescaleDB to avoid a local Postgres clash.
- LF→CRLF git warnings on Windows are benign.

## Final state (end of session)

Phases 01–12 closed. Phase 13 in progress: SwapSpec frozen, virgin holdout
imported and bounds verified, spread calibration waiting on ≥2 more NY AM tick
sessions (1/3 minimum collected). The candidate (`CANDIDATE_CONFIG_2026_07_18`)
is test-locked, the cost profile is partially frozen (spread/slippage/commission
done, swap done), and the verdict machinery is built and guard-tested. 

Next: collect NY AM ticks on 2–4 more days (12:00–16:00 UTC, 1/3 minimum done
with 14,044 ticks on Mon 2026-07-27) → re-run `calibrate-spread.ts` → freeze
final spread → final pre-read summary → user approval → the single
`--verdict-holdout` read.
