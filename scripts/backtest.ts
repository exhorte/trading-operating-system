/**
 * Backtest runner (Phase 11): replays the SAME pure TS engines the platform
 * runs live — ICT/SMC context (lib/analysis), FTMO risk (lib/risk), strategy
 * stub (lib/mock/signals) — bar by bar over candles stored in TimescaleDB,
 * simulates each approved signal's outcome, and persists the run + trades.
 *
 *   npx tsx scripts/backtest.ts [--symbol XAUUSDm] [--timeframe M15]
 *                               [--strategy sampler|trigger] [--every N]
 *                               [--max-bars 32] [--from ISO] [--to ISO]
 *
 * --strategy sampler (default): the periodic control arm (lib/mock/signals).
 * --strategy trigger: the iteration-1 ICT FVG-retest entry (lib/strategy),
 *   which defaults --every to 1 (a retest can land on any bar).
 * --sessions a,b: strategy-layer session allowlist (iteration 2, e.g.
 *   --sessions new_york_am); omitted = all sessions.
 *
 * HYPOTHESIS TESTING ONLY: engine v0.1, no spread/slippage/costs, binary
 * SL/TP exits (both-touch bars = conservative loss). Results grade signal
 * quality, never account performance.
 */

import { createHash, randomUUID } from "node:crypto";
import { execSync } from "node:child_process";
import { Client } from "pg";
import { analyzeMarketContext, DEFAULT_SESSION_WINDOWS } from "@/lib/analysis";
import { sessionEnabled, sessionForTimestamp } from "@/lib/analysis/sessions";
import { defaultRiskPolicy, evaluateRiskState, evaluateSignalRisk } from "@/lib/risk";
import { mockStrategySignal } from "@/lib/mock/signals";
import { DEFAULT_TRIGGER_CONFIG, evaluateTrigger } from "@/lib/strategy";
import type { TradingSession } from "@/lib/domain/primitives";
import { simulateTradeOutcome, type SimulatedTrade } from "@/lib/backtest/outcome";
import { computeMetrics } from "@/lib/backtest/metrics";
import { clipHoldout, onlyHoldout, VIRGIN_HOLDOUT } from "@/lib/backtest/holdout";
import {
  FROZEN_COST_PROFILE_2026_07_18,
  STRESS_COST_PROFILE,
  roundTripCostR,
  rolloverCrossings,
  swapCostR,
} from "@/lib/backtest/costs";
import { classifyVerdict, VERDICT_CRITERIA_2026_07_18 } from "@/lib/backtest/verdict";
import { CANDIDATE_CONFIG_2026_07_18 } from "@/lib/strategy";
import type { MarketContextState } from "@/lib/domain/analysis";
import type { Candle } from "@/lib/domain/market";
import type { StrategySignal } from "@/lib/domain/strategy";

const CONNECTION =
  process.env.TRADINGOS_DB ??
  "postgres://tradingos:tradingos_dev@localhost:5433/tradingos";

const WINDOW = 300; // same rolling window as the live clients
const INITIAL_BALANCE = 10_000;
/** XAUUSD tick size (MVP: single symbol). Generalise via SymbolMetadata later. */
const TICK_SIZE = 0.01;

/** Which strategy arm produced a run — recorded in engine_version so runs are
 *  never ambiguous. `sampler` is the periodic control; `trigger` the treatment. */
type StrategyArm = "sampler" | "trigger";

function engineVersion(arm: StrategyArm): string {
  return arm === "trigger"
    ? "ict-smc v0.1 / risk v0.1 / trigger-strategy v0.1"
    : "ict-smc v0.1 / risk v0.1 / stub-strategy";
}

interface Args {
  /** Single-read verdict mode (Phase 13): frozen candidate on the virgin
   *  holdout, no overrides, immutable outcome. */
  verdictHoldout: boolean;
  symbol: string;
  timeframe: string;
  strategy: StrategyArm;
  /** Strategy-layer session allowlist (iteration 2+); null = all sessions. */
  sessions: TradingSession[] | null;
  every: number; // evaluate a signal every N bars
  maxBars: number; // outcome horizon
  from: string | null; // ISO date filter (train-only refinement runs)
  to: string | null;
}

function parseArgs(): Args {
  const get = (flag: string, fallback: string) => {
    const i = process.argv.indexOf(flag);
    return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
  };
  const verdictHoldout = process.argv.includes("--verdict-holdout");
  if (verdictHoldout) {
    // The verdict accepts EXACTLY the frozen candidate — every override flag
    // is rejected, not ignored (user spec 2026-07-18).
    const forbidden = ["--strategy", "--sessions", "--every", "--from", "--to", "--max-bars", "--symbol", "--timeframe"];
    const present = forbidden.filter((f) => process.argv.includes(f));
    if (present.length > 0) {
      console.error(`[verdict] REFUSED: --verdict-holdout accepts no override flags (got ${present.join(", ")})`);
      process.exit(1);
    }
  }
  const strategy = (get("--strategy", "sampler") === "trigger" ? "trigger" : "sampler") as StrategyArm;
  // A retest lands on ANY bar, so the trigger must see every bar; the sampler
  // keeps its historical every-8 cadence unless overridden.
  const everyDefault = strategy === "trigger" ? "1" : "8";
  const sessionsCsv = get("--sessions", "");
  return {
    verdictHoldout,
    symbol: get("--symbol", "XAUUSDm"),
    timeframe: get("--timeframe", "M15"),
    strategy,
    sessions: sessionsCsv
      ? (sessionsCsv.split(",").map((s) => s.trim()) as TradingSession[])
      : null,
    every: Number(get("--every", everyDefault)),
    maxBars: Number(get("--max-bars", "32")),
    from: get("--from", "") || null,
    to: get("--to", "") || null,
  };
}

/** Chronological 60/20/20 split boundaries over the eligible signal range
 *  (Phase 12 anti-overfitting discipline — ADR 0013). Time-based, not
 *  trade-count-based, so trade density never leaks into the split. */
function splitBoundaries(firstEligible: string, lastEligible: string): { trainEnd: number; valEnd: number } {
  const start = Date.parse(firstEligible);
  const end = Date.parse(lastEligible);
  return { trainEnd: start + (end - start) * 0.6, valEnd: start + (end - start) * 0.8 };
}

function splitFor(timeIso: string, b: { trainEnd: number; valEnd: number }): "train" | "validation" | "oos" {
  const t = Date.parse(timeIso);
  return t <= b.trainEnd ? "train" : t <= b.valEnd ? "validation" : "oos";
}

/** Frozen diagnostic features at signal time. Key set documented in ADR 0013 —
 *  keep stable, the report depends on them. */
function extractFeatures(signal: StrategySignal, context: MarketContextState): Record<string, unknown> {
  const alignedDir = signal.side === "buy" ? "bullish" : "bearish";
  const withBias = context.bias === "bearish" ? "sell" : "buy";
  const fvgs = context.activeFairValueGaps.filter((g) => g.direction === alignedDir);
  const obs = context.activeOrderBlocks.filter((o) => o.direction === alignedDir);
  return {
    session: context.session,
    bias: context.bias,
    sideVsBias: signal.side === withBias ? "with" : "counter",
    structure: context.lastStructureShift
      ? context.lastStructureShift.kind === "break_of_structure" ? "bos" : "choch"
      : "none",
    stopDistance: Math.round(Math.abs(signal.entryPrice - signal.stopLoss) * 100) / 100,
    scoreComponents: Object.fromEntries(context.scoreBreakdown.map((c) => [c.label, c.score])),
    fvgAligned: fvgs.length,
    fvgInside: fvgs.some((g) => signal.entryPrice >= g.low && signal.entryPrice <= g.high),
    obAligned: obs.length,
    obInside: obs.some((o) => signal.entryPrice >= o.low && signal.entryPrice <= o.high),
    liqKinds: [...new Set(context.activeLiquidityLevels.map((l) => l.kind))],
  };
}

interface TradeRecord {
  trade: SimulatedTrade;
  signalTime: string;
  side: string;
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
  volume: number;
  score: number;
  reason: string;
  features: Record<string, unknown>;
}

interface RejectionRecord {
  seq: number;
  signalTime: string;
  side: string;
  score: number;
  session: string;
  reason: string;
}

/** Reference server midnights (UTC) used to DETECT rollover crossings when
 *  the frozen profile has no swap spec: GMT+2 and GMT+3 brokers. If a trade
 *  crosses either, the verdict refuses itself rather than assume a zero swap
 *  (user invariant 2026-07-18). */
const REFERENCE_ROLLOVER_HOURS_UTC = [21, 22];

function stableStringify(value: unknown): string {
  return JSON.stringify(value, (_k, v) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(
          Object.entries(v as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)),
        )
      : v,
  );
}

function sha256(s: string): string {
  return createHash("sha256").update(s).digest("hex");
}

/**
 * Phase 13 single-read verdict (user spec 2026-07-18). Deliberately does NOT
 * share the ordinary walk-forward code path: the verdict must be auditable in
 * isolation and immune to ordinary-mode flags. Sequence:
 * clean-tree + commit hash → single-read check (DB PK is the arbiter of
 * "consumed") → audited attempt row → holdout candles only → silent
 * walk-forward with EXACTLY the frozen candidate → swap invariant BEFORE any
 * metric → costs → gross+net+stress metrics → pre-registered classification →
 * immutable verdict row → the one and only read is printed.
 */
async function runVerdictHoldout(client: Client): Promise<void> {
  const profile = FROZEN_COST_PROFILE_2026_07_18;
  const criteria = VERDICT_CRITERIA_2026_07_18;
  const maxBars = 32; // the default horizon, deliberately not overridable here

  // Guard: the verdict records the commit hash, so the tree must be clean.
  let commitHash: string;
  try {
    const dirty = execSync("git status --porcelain", { encoding: "utf-8" }).trim();
    if (dirty.length > 0) {
      console.error("[verdict] REFUSED: working tree is dirty — the verdict records the commit hash, commit first.");
      process.exit(1);
    }
    commitHash = execSync("git rev-parse HEAD", { encoding: "utf-8" }).trim();
  } catch (err) {
    console.error("[verdict] REFUSED: cannot resolve git state:", (err as Error).message);
    process.exit(1);
  }

  // Guard: single read — enforced by the holdout_verdicts primary key; this
  // check just gives a clear message before the INSERT would fail anyway.
  const existing = await client.query(
    "SELECT verdict, run_id, created_at FROM holdout_verdicts WHERE holdout_from = $1 AND holdout_to = $2",
    [VIRGIN_HOLDOUT.fromUtc, VIRGIN_HOLDOUT.toUtc],
  );
  if (existing.rows.length > 0) {
    const v = existing.rows[0];
    console.error(`[verdict] REFUSED: the holdout was already read — ${v.verdict} (run ${v.run_id}, ${v.created_at}). Verdicts are immutable.`);
    process.exit(1);
  }

  const attemptRow = await client.query(
    "INSERT INTO holdout_attempts (holdout_from, holdout_to, status) VALUES ($1, $2, 'started') RETURNING id",
    [VIRGIN_HOLDOUT.fromUtc, VIRGIN_HOLDOUT.toUtc],
  );
  const attemptId = attemptRow.rows[0].id as number;
  const mark = (status: string, detail: string, runId: string | null = null) =>
    client.query(
      "UPDATE holdout_attempts SET status = $2, detail = $3, run_id = $4, finished_at = now() WHERE id = $1",
      [attemptId, status, detail, runId],
    );

  try {
    const { rows } = await client.query(
      `SELECT symbol, timeframe, open_time AS "openTime", open, high, low, close, volume, closed
       FROM candles
       WHERE symbol = $1 AND timeframe = $2 AND closed = true
         AND open_time >= $3::timestamptz AND open_time < $4::timestamptz
       ORDER BY open_time ASC`,
      [VIRGIN_HOLDOUT.symbol, VIRGIN_HOLDOUT.timeframe, VIRGIN_HOLDOUT.fromUtc, VIRGIN_HOLDOUT.toUtc],
    );
    const candles: Candle[] = onlyHoldout(
      rows.map((r) => ({
        symbol: r.symbol, timeframe: r.timeframe,
        openTime: new Date(r.openTime).toISOString(),
        open: Number(r.open), high: Number(r.high), low: Number(r.low), close: Number(r.close),
        volume: Number(r.volume), closed: r.closed,
      })),
    );
    if (candles.length < WINDOW + maxBars + 500) {
      await mark("refused_guard", `only ${candles.length} holdout candles — import the anterior history first`);
      console.error(`[verdict] REFUSED: only ${candles.length} holdout candles in the DB — import 2024-06-01 → 2025-06-06 first.`);
      process.exit(1);
    }
    const datasetHash = sha256(
      candles.map((c) => `${c.openTime}|${c.open}|${c.high}|${c.low}|${c.close}|${c.volume}`).join("\n"),
    );

    // --- Silent walk-forward with EXACTLY the frozen candidate. ---
    const policy = defaultRiskPolicy("backtest");
    const runId = `bt-verdict-${Date.now().toString(36)}-${randomUUID().slice(0, 8)}`;
    interface VerdictTradeRecord {
      trade: SimulatedTrade;
      signalTime: string;
      side: "buy" | "sell";
      entryPrice: number;
      stopLoss: number;
      takeProfit: number;
      volume: number;
      score: number;
      reason: string;
      features: Record<string, unknown>;
      riskDistance: number;
    }
    const records: VerdictTradeRecord[] = [];
    let signalCount = 0;

    for (let i = WINDOW; i < candles.length - maxBars; i += 1) {
      const window = candles.slice(i - WINDOW, i + 1);
      const bar = candles[i];
      const context = analyzeMarketContext({
        symbol: VIRGIN_HOLDOUT.symbol,
        timeframe: VIRGIN_HOLDOUT.timeframe as Candle["timeframe"],
        candles: window,
      });
      const result = evaluateTrigger({
        window, context, accountId: "verdict", tickSize: TICK_SIZE,
        seq: signalCount + 1, runId, config: CANDIDATE_CONFIG_2026_07_18,
      });
      if (!result) {
        continue;
      }
      signalCount += 1;
      const { signal } = result;

      const session = sessionForTimestamp(bar.openTime, DEFAULT_SESSION_WINDOWS);
      const riskState = evaluateRiskState({
        policy, initialBalance: INITIAL_BALANCE, dayStartEquity: INITIAL_BALANCE,
        equity: INITIAL_BALANCE, balance: INITIAL_BALANCE, positions: [],
        tradesToday: null, consecutiveLosses: null, spreadPoints: null,
        session, sessionTradingEnabled: sessionEnabled(session, DEFAULT_SESSION_WINDOWS),
        now: bar.openTime,
      });
      const decision = evaluateSignalRisk({
        signalId: signal.signalId, accountId: "verdict",
        entryPrice: signal.entryPrice, stopLoss: signal.stopLoss,
        balance: INITIAL_BALANCE, state: riskState, policy, now: bar.openTime,
      });
      if (!decision.approved || decision.approvedVolume === null) {
        continue;
      }
      const trade = simulateTradeOutcome({
        side: signal.side, entryPrice: signal.entryPrice, stopLoss: signal.stopLoss,
        takeProfit: signal.takeProfit,
        futureCandles: candles.slice(i + 1, i + 1 + maxBars), maxBars,
      });
      if (!trade) {
        continue;
      }
      records.push({
        trade, signalTime: bar.openTime, side: signal.side,
        entryPrice: signal.entryPrice, stopLoss: signal.stopLoss, takeProfit: signal.takeProfit,
        volume: decision.approvedVolume, score: signal.score, reason: decision.reason,
        features: { ...extractFeatures(signal, context), ...result.setup },
        riskDistance: Math.abs(signal.entryPrice - signal.stopLoss),
      });
    }

    // --- Swap invariant BEFORE any metric (user 2026-07-18): no trade may
    // cross a rollover with swap unmodeled — refuse instead of assuming 0. ---
    const crossingHours = profile.swap !== null ? [profile.swap.rolloverHourUtc] : REFERENCE_ROLLOVER_HOURS_UTC;
    const crossingCounts = records.map((r) =>
      Math.max(
        ...crossingHours.map((hour) =>
          rolloverCrossings({
            signalOpenTimeIso: r.signalTime, barsHeld: r.trade.barsHeld, barMinutes: 15,
            swap: { rolloverHourUtc: hour, longUsdPerLotPerNight: 0, shortUsdPerLotPerNight: 0, tripleSwapWeekdayUtc: 3 },
          }),
        ),
      ),
    );
    const crossingTrades = crossingCounts.filter((c) => c > 0).length;
    if (profile.swap === null && crossingTrades > 0) {
      await mark("refused_swap_invariant", `${crossingTrades}/${records.length} trades cross a 21/22 UTC rollover; swap unmodeled`);
      console.error(
        `[verdict] REFUSED (swap invariant): ${crossingTrades} of ${records.length} trades cross a possible rollover ` +
        `(21:00/22:00 UTC) and the frozen profile models no swap. NO metrics were computed or revealed — the holdout stays virgin. ` +
        `Provide Exness XAUUSDm swap rates (long/short USD per lot per night + server rollover hour), re-freeze the cost profile, commit, retry.`,
      );
      process.exit(1);
    }

    // --- Costs → net. From here on, metrics exist. ---
    const netTrades = records.map((r, idx) => {
      const costR = roundTripCostR(profile, r.riskDistance) +
        swapCostR({ profile, side: r.side, crossings: crossingCounts[idx], riskDistance: r.riskDistance });
      return {
        costR: Math.round(costR * 10_000) / 10_000,
        netR: Math.round((r.trade.rMultiple - costR) * 10_000) / 10_000,
        side: r.side,
        month: r.signalTime.slice(0, 7),
      };
    });
    const gross = computeMetrics(records.map((r) => r.trade));
    const verdict = classifyVerdict(netTrades.map((t) => ({ netR: t.netR, side: t.side, month: t.month })), criteria);
    const stressNet = records.map((r, idx) => {
      const costR = roundTripCostR(STRESS_COST_PROFILE, r.riskDistance) +
        swapCostR({ profile: STRESS_COST_PROFILE, side: r.side, crossings: crossingCounts[idx], riskDistance: r.riskDistance });
      return r.trade.rMultiple - costR;
    });
    const stress = {
      profile: STRESS_COST_PROFILE.name,
      netExpectancyR: Math.round((stressNet.reduce((s, v) => s + v, 0) / Math.max(1, stressNet.length)) * 10_000) / 10_000,
      netCumulativeR: Math.round(stressNet.reduce((s, v) => s + v, 0) * 100) / 100,
    };

    const candidateHash = sha256(stableStringify(CANDIDATE_CONFIG_2026_07_18));
    const costProfileHash = sha256(stableStringify(profile));

    // --- Persist: run row, trades (split='holdout'), immutable verdict. ---
    await client.query(
      `INSERT INTO backtest_runs (run_id, symbol, timeframe, engine_version, config, from_time, to_time,
         candle_count, signal_count, approved_count, trade_count, win_count, loss_count, timeout_count,
         both_touch_count, win_rate, avg_r, expectancy_r, max_consec_losses, cumulative_r)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)`,
      [
        runId, VIRGIN_HOLDOUT.symbol, VIRGIN_HOLDOUT.timeframe,
        "ict-smc v0.1 / risk v0.1 / trigger-strategy v0.1 / VERDICT",
        JSON.stringify({
          mode: "verdict-holdout", holdout: VIRGIN_HOLDOUT, window: WINDOW, maxBars, every: 1,
          candidate: CANDIDATE_CONFIG_2026_07_18, costProfile: profile, criteria,
          hashes: { commitHash, datasetHash, candidateHash, costProfileHash },
        }),
        candles[0].openTime, candles.at(-1)!.openTime, candles.length,
        signalCount, records.length, gross.tradeCount, gross.winCount, gross.lossCount,
        gross.timeoutCount, gross.bothTouchCount, gross.winRate, gross.avgR, gross.expectancyR,
        gross.maxConsecutiveLosses, gross.cumulativeR,
      ],
    );
    for (let seq = 0; seq < records.length; seq += 1) {
      const r = records[seq];
      const n = netTrades[seq];
      await client.query(
        `INSERT INTO backtest_trades (run_id, seq, signal_time, side, entry_price, stop_loss, take_profit,
           volume, outcome, both_touch, r_multiple, bars_held, exit_price, score, reason, features, split,
           cost_r, net_r_multiple)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb,$17,$18,$19)`,
        [
          runId, seq, r.signalTime, r.side, r.entryPrice, r.stopLoss, r.takeProfit,
          r.volume, r.trade.outcome, r.trade.bothTouch, r.trade.rMultiple, r.trade.barsHeld,
          r.trade.exitPrice, r.score, r.reason, JSON.stringify(r.features), "holdout",
          n.costR, n.netR,
        ],
      );
    }
    await client.query(
      `INSERT INTO holdout_verdicts (holdout_from, holdout_to, verdict, run_id, commit_hash, dataset_hash,
         candidate_hash, cost_profile_hash, metrics, stress, criteria, reasons)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11::jsonb,$12::jsonb)`,
      [
        VIRGIN_HOLDOUT.fromUtc, VIRGIN_HOLDOUT.toUtc, verdict.outcome, runId,
        commitHash, datasetHash, candidateHash, costProfileHash,
        JSON.stringify({ gross, net: verdict.metrics }), JSON.stringify(stress),
        JSON.stringify(criteria), JSON.stringify(verdict.reasons),
      ],
    );
    await mark("completed", verdict.outcome, runId);

    // --- THE read. Printed once, after everything is durably recorded. ---
    console.log("═".repeat(72));
    console.log(`[verdict] ${verdict.outcome} — run ${runId}`);
    console.log("═".repeat(72));
    console.log(`holdout   ${VIRGIN_HOLDOUT.fromUtc} → ${VIRGIN_HOLDOUT.toUtc} (${candles.length} candles)`);
    console.log(`hashes    commit=${commitHash.slice(0, 12)} dataset=${datasetHash.slice(0, 12)} candidate=${candidateHash.slice(0, 12)} costs=${costProfileHash.slice(0, 12)}`);
    console.log(`gross     n=${gross.tradeCount} win=${gross.winRate}% exp=${gross.expectancyR}R cum=${gross.cumulativeR}R maxConsecLoss=${gross.maxConsecutiveLosses}`);
    console.log(`net       n=${verdict.metrics.n} exp=${verdict.metrics.netExpectancyR}R cum=${verdict.metrics.netCumulativeR}R ` +
      `BUY n=${verdict.metrics.buyN}/${verdict.metrics.buyExpectancyR}R SELL n=${verdict.metrics.sellN}/${verdict.metrics.sellExpectancyR}R`);
    console.log(`bootstrap [${verdict.metrics.bootstrapLower}R, ${verdict.metrics.bootstrapUpper}R] width=${verdict.metrics.bootstrapWidth}R`);
    console.log(`month     max share=${verdict.metrics.maxMonthShare === null ? "n/a" : `${Math.round(verdict.metrics.maxMonthShare * 100)}% (${verdict.metrics.maxMonth})`}`);
    console.log(`stress    exp=${stress.netExpectancyR}R cum=${stress.netCumulativeR}R (informative only — never modifies the candidate)`);
    console.log(`reasons   ${verdict.reasons.join(" · ")}`);
    console.log("═".repeat(72));
    console.log("[verdict] recorded immutably in holdout_verdicts — this holdout is now consumed.");
  } catch (err) {
    await mark("aborted_technical", String((err as Error)?.message ?? err));
    console.error("[verdict] technical failure before the verdict row was written — no metrics were revealed; an audited retry is permitted.");
    throw err;
  }
}

async function main(): Promise<void> {
  const args = parseArgs();
  const client = new Client({ connectionString: CONNECTION });
  await client.connect();

  if (args.verdictHoldout) {
    try {
      await runVerdictHoldout(client);
    } finally {
      await client.end();
    }
    return;
  }

  const filters: string[] = [];
  const params: unknown[] = [args.symbol, args.timeframe];
  if (args.from) {
    params.push(args.from);
    filters.push(`AND open_time >= $${params.length}::timestamptz`);
  }
  if (args.to) {
    params.push(args.to);
    filters.push(`AND open_time <= $${params.length}::timestamptz`);
  }
  const { rows } = await client.query(
    `SELECT symbol, timeframe, open_time AS "openTime", open, high, low, close, volume, closed
     FROM candles WHERE symbol = $1 AND timeframe = $2 AND closed = true ${filters.join(" ")}
     ORDER BY open_time ASC`,
    params,
  );
  const loaded: Candle[] = rows.map((r) => ({
    symbol: r.symbol,
    timeframe: r.timeframe,
    openTime: new Date(r.openTime).toISOString(),
    open: Number(r.open),
    high: Number(r.high),
    low: Number(r.low),
    close: Number(r.close),
    volume: Number(r.volume),
    closed: r.closed,
  }));
  // VIRGIN HOLDOUT LOCK (Phase 13): ordinary runs can never see holdout
  // candles — exploration is impossible by construction, not by discipline.
  // The one-shot --verdict-holdout mode is the only reader.
  const { kept: candles, removed } = clipHoldout(loaded);
  if (removed > 0 && candles.length === 0) {
    console.error(`[backtest] REFUSED: the requested range lies entirely inside the virgin holdout (${VIRGIN_HOLDOUT.fromUtc} → ${VIRGIN_HOLDOUT.toUtc}). Only --verdict-holdout may read it, once.`);
    process.exit(1);
  }
  if (removed > 0) {
    console.warn(`[backtest] ⚠ HOLDOUT LOCK: ${removed} candles inside the virgin holdout were clipped from this run.`);
  }
  if (candles.length < WINDOW + args.maxBars) {
    console.error(`[backtest] not enough candles (${candles.length}); import history first`);
    process.exit(1);
  }
  console.log(`[backtest] ${candles.length} candles ${candles[0].openTime} → ${candles.at(-1)!.openTime}`);

  const policy = defaultRiskPolicy("backtest");
  const account = {
    accountId: "backtest",
    label: "Backtest",
    broker: "backtest",
    currency: "USD",
    balance: INITIAL_BALANCE,
    equity: INITIAL_BALANCE,
    dailyPnl: 0,
    dailyDrawdownPercent: 0,
    totalDrawdownPercent: 0,
    openRiskPercent: 0,
  };

  let signalCount = 0;
  let approvedCount = 0;
  const records: TradeRecord[] = [];
  const rejections: RejectionRecord[] = [];
  const runId = `bt-${Date.now().toString(36)}-${randomUUID().slice(0, 8)}`;

  // Chronological 60/20/20 split over the eligible signal range (ADR 0013).
  const boundaries = splitBoundaries(
    candles[WINDOW].openTime,
    candles[candles.length - args.maxBars - 1].openTime,
  );

  // Walk forward: at bar i, the engine sees ONLY candles up to i (the
  // engines' own no-look-ahead invariant guards the window content too).
  for (let i = WINDOW; i < candles.length - args.maxBars; i += args.every) {
    const window = candles.slice(i - WINDOW, i + 1);
    const bar = candles[i];
    const context = analyzeMarketContext({
      symbol: args.symbol,
      timeframe: args.timeframe as Candle["timeframe"],
      candles: window,
    });

    // Sampler (control): emits every bar — signalCount is per-bar, preserving
    // the arm's exact historical behaviour. Trigger (treatment): emits only
    // when a full setup is present, so a null bar is "no setup", not a
    // rejection, and does not consume a sequence number.
    let signal: StrategySignal | null;
    let triggerSetup: Record<string, unknown> | null = null;
    if (args.strategy === "trigger") {
      const result = evaluateTrigger({
        window,
        context,
        accountId: "backtest",
        tickSize: TICK_SIZE,
        seq: signalCount + 1,
        runId,
        config: { ...DEFAULT_TRIGGER_CONFIG, allowedSessions: args.sessions },
      });
      if (!result) {
        continue;
      }
      signal = result.signal;
      triggerSetup = { ...result.setup };
      signalCount += 1;
    } else {
      signalCount += 1;
      signal = mockStrategySignal({
        context,
        account,
        price: bar.close,
        seq: signalCount,
        runId,
      });
    }

    const session = sessionForTimestamp(bar.openTime, DEFAULT_SESSION_WINDOWS);
    const riskState = evaluateRiskState({
      policy,
      initialBalance: INITIAL_BALANCE,
      dayStartEquity: INITIAL_BALANCE,
      equity: INITIAL_BALANCE,
      balance: INITIAL_BALANCE,
      positions: [],
      tradesToday: null,
      consecutiveLosses: null,
      spreadPoints: null, // no historical spread in MVP — gate reports n/a
      session,
      sessionTradingEnabled: sessionEnabled(session, DEFAULT_SESSION_WINDOWS),
      now: bar.openTime,
    });
    const decision = evaluateSignalRisk({
      signalId: signal.signalId,
      accountId: "backtest",
      entryPrice: signal.entryPrice,
      stopLoss: signal.stopLoss,
      balance: INITIAL_BALANCE,
      state: riskState,
      policy,
      now: bar.openTime,
    });
    if (!decision.approved || decision.approvedVolume === null) {
      rejections.push({
        seq: signalCount,
        signalTime: bar.openTime,
        side: signal.side,
        score: signal.score,
        session,
        reason: decision.reason,
      });
      continue;
    }
    approvedCount += 1;

    const trade = simulateTradeOutcome({
      side: signal.side,
      entryPrice: signal.entryPrice,
      stopLoss: signal.stopLoss,
      takeProfit: signal.takeProfit,
      futureCandles: candles.slice(i + 1, i + 1 + args.maxBars),
      maxBars: args.maxBars,
    });
    if (!trade) {
      continue;
    }
    records.push({
      trade,
      signalTime: bar.openTime,
      side: signal.side,
      entryPrice: signal.entryPrice,
      stopLoss: signal.stopLoss,
      takeProfit: signal.takeProfit,
      volume: decision.approvedVolume,
      score: signal.score,
      reason: decision.reason,
      // Trigger runs append the EXACT setup traded (fvgSize/fvgAgeBars/
      // shiftAgeBars/retestDepthPercent/atr/stopBuffer…) — additive keys on
      // top of the frozen ADR 0013 set. The generic fvgInside stays but
      // measures a different notion (entry inside ANY aligned gap at signal
      // time); the trigger's own gap lives in these keys.
      features: { ...extractFeatures(signal, context), ...(triggerSetup ?? {}) },
    });
  }

  const metrics = computeMetrics(records.map((r) => r.trade));

  await client.query(
    `INSERT INTO backtest_runs (run_id, symbol, timeframe, engine_version, config, from_time, to_time,
       candle_count, signal_count, approved_count, trade_count, win_count, loss_count, timeout_count,
       both_touch_count, win_rate, avg_r, expectancy_r, max_consec_losses, cumulative_r)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)`,
    [
      runId, args.symbol, args.timeframe, engineVersion(args.strategy),
      JSON.stringify({
        strategy: args.strategy,
        sessions: args.sessions,
        every: args.every,
        maxBars: args.maxBars,
        window: WINDOW,
        from: args.from,
        to: args.to,
        splits: {
          trainEnd: new Date(boundaries.trainEnd).toISOString(),
          valEnd: new Date(boundaries.valEnd).toISOString(),
          ratios: "60/20/20 chronological",
        },
        note: "no spread/slippage/costs; both-touch = conservative loss",
      }),
      candles[0].openTime, candles.at(-1)!.openTime,
      candles.length, signalCount, approvedCount,
      metrics.tradeCount, metrics.winCount, metrics.lossCount, metrics.timeoutCount,
      metrics.bothTouchCount, metrics.winRate, metrics.avgR, metrics.expectancyR,
      metrics.maxConsecutiveLosses, metrics.cumulativeR,
    ],
  );
  for (let seq = 0; seq < records.length; seq += 1) {
    const r = records[seq];
    await client.query(
      `INSERT INTO backtest_trades (run_id, seq, signal_time, side, entry_price, stop_loss, take_profit,
         volume, outcome, both_touch, r_multiple, bars_held, exit_price, score, reason, features, split)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb,$17)`,
      [
        runId, seq, r.signalTime, r.side, r.entryPrice, r.stopLoss, r.takeProfit,
        r.volume, r.trade.outcome, r.trade.bothTouch, r.trade.rMultiple,
        r.trade.barsHeld, r.trade.exitPrice, r.score, r.reason,
        JSON.stringify(r.features), splitFor(r.signalTime, boundaries),
      ],
    );
  }
  for (const rej of rejections) {
    await client.query(
      `INSERT INTO backtest_rejections (run_id, seq, signal_time, side, score, session, reason, split)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`,
      [
        runId, rej.seq, rej.signalTime, rej.side, rej.score, rej.session, rej.reason,
        splitFor(rej.signalTime, boundaries),
      ],
    );
  }
  await client.end();

  // The whole-period metrics are PERSISTED (the run row is the record, read at
  // --unlock-oos) but never PRINTED: this summary used to report them over all
  // trades incl. OOS, leaking out-of-sample performance on every single run
  // before the report was even opened — fixed 2026-07-17 (ADR 0013).
  const reported = records
    .filter((r) => splitFor(r.signalTime, boundaries) !== "oos")
    .map((r) => r.trade);
  const shown = computeMetrics(reported);
  const oosCount = metrics.tradeCount - reported.length;

  console.log(`[backtest] run ${runId} persisted (strategy=${args.strategy}, every=${args.every}, sessions=${args.sessions?.join(",") ?? "all"})`);
  console.log(`[backtest] signals=${signalCount} approved=${approvedCount} rejected=${rejections.length}`);
  console.log(`[backtest] splits: train ≤ ${new Date(boundaries.trainEnd).toISOString()} < validation ≤ ${new Date(boundaries.valEnd).toISOString()} < oos`);
  console.log(`[backtest] TRAIN+VALIDATION (${shown.tradeCount} trades): winRate=${shown.winRate}% avgR=${shown.avgR} expectancy=${shown.expectancyR}R cumulative=${shown.cumulativeR}R maxConsecLosses=${shown.maxConsecutiveLosses} bothTouch=${shown.bothTouchCount}`);
  console.log(`[backtest] 🔒 ${oosCount} OOS trades reserved — metrics withheld until scripts/backtest-report.ts ${runId} --unlock-oos`);
  console.log(`[backtest] next: npx tsx scripts/backtest-report.ts ${runId}`);
  console.log("[backtest] HYPOTHESIS ONLY — no costs modeled, engine v0.1");
}

main().catch((err) => {
  console.error("[backtest] failed:", err.message ?? err);
  process.exit(1);
});
