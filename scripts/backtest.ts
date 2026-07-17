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
 *
 * HYPOTHESIS TESTING ONLY: engine v0.1, no spread/slippage/costs, binary
 * SL/TP exits (both-touch bars = conservative loss). Results grade signal
 * quality, never account performance.
 */

import { randomUUID } from "node:crypto";
import { Client } from "pg";
import { analyzeMarketContext, DEFAULT_SESSION_WINDOWS } from "@/lib/analysis";
import { sessionEnabled, sessionForTimestamp } from "@/lib/analysis/sessions";
import { defaultRiskPolicy, evaluateRiskState, evaluateSignalRisk } from "@/lib/risk";
import { mockStrategySignal } from "@/lib/mock/signals";
import { evaluateTrigger } from "@/lib/strategy";
import { simulateTradeOutcome, type SimulatedTrade } from "@/lib/backtest/outcome";
import { computeMetrics } from "@/lib/backtest/metrics";
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
  symbol: string;
  timeframe: string;
  strategy: StrategyArm;
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
  const strategy = (get("--strategy", "sampler") === "trigger" ? "trigger" : "sampler") as StrategyArm;
  // A retest lands on ANY bar, so the trigger must see every bar; the sampler
  // keeps its historical every-8 cadence unless overridden.
  const everyDefault = strategy === "trigger" ? "1" : "8";
  return {
    symbol: get("--symbol", "XAUUSDm"),
    timeframe: get("--timeframe", "M15"),
    strategy,
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

async function main(): Promise<void> {
  const args = parseArgs();
  const client = new Client({ connectionString: CONNECTION });
  await client.connect();

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
  const candles: Candle[] = rows.map((r) => ({
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
    if (args.strategy === "trigger") {
      signal = evaluateTrigger({
        window,
        context,
        accountId: "backtest",
        tickSize: TICK_SIZE,
        seq: signalCount + 1,
        runId,
      });
      if (!signal) {
        continue;
      }
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
      features: extractFeatures(signal, context),
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

  console.log(`[backtest] run ${runId} persisted (strategy=${args.strategy}, every=${args.every})`);
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
