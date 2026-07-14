/**
 * Backtest runner (Phase 11): replays the SAME pure TS engines the platform
 * runs live — ICT/SMC context (lib/analysis), FTMO risk (lib/risk), strategy
 * stub (lib/mock/signals) — bar by bar over candles stored in TimescaleDB,
 * simulates each approved signal's outcome, and persists the run + trades.
 *
 *   npx tsx scripts/backtest.ts [--symbol XAUUSDm] [--timeframe M15]
 *                               [--every 8] [--max-bars 32]
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
import { simulateTradeOutcome, type SimulatedTrade } from "@/lib/backtest/outcome";
import { computeMetrics } from "@/lib/backtest/metrics";
import type { Candle } from "@/lib/domain/market";

const CONNECTION =
  process.env.TRADINGOS_DB ??
  "postgres://tradingos:tradingos_dev@localhost:5433/tradingos";

const ENGINE_VERSION = "ict-smc v0.1 / risk v0.1 / stub-strategy";
const WINDOW = 300; // same rolling window as the live clients
const INITIAL_BALANCE = 10_000;

interface Args {
  symbol: string;
  timeframe: string;
  every: number; // evaluate a signal every N bars
  maxBars: number; // outcome horizon
}

function parseArgs(): Args {
  const get = (flag: string, fallback: string) => {
    const i = process.argv.indexOf(flag);
    return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
  };
  return {
    symbol: get("--symbol", "XAUUSDm"),
    timeframe: get("--timeframe", "M15"),
    every: Number(get("--every", "8")),
    maxBars: Number(get("--max-bars", "32")),
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
}

async function main(): Promise<void> {
  const args = parseArgs();
  const client = new Client({ connectionString: CONNECTION });
  await client.connect();

  const { rows } = await client.query(
    `SELECT symbol, timeframe, open_time AS "openTime", open, high, low, close, volume, closed
     FROM candles WHERE symbol = $1 AND timeframe = $2 AND closed = true
     ORDER BY open_time ASC`,
    [args.symbol, args.timeframe],
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
  const runId = `bt-${Date.now().toString(36)}-${randomUUID().slice(0, 8)}`;

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

    signalCount += 1;
    const signal = mockStrategySignal({
      context,
      account,
      price: bar.close,
      seq: signalCount,
      runId,
    });

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
    });
  }

  const metrics = computeMetrics(records.map((r) => r.trade));

  await client.query(
    `INSERT INTO backtest_runs (run_id, symbol, timeframe, engine_version, config, from_time, to_time,
       candle_count, signal_count, approved_count, trade_count, win_count, loss_count, timeout_count,
       both_touch_count, win_rate, avg_r, expectancy_r, max_consec_losses, cumulative_r)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20)`,
    [
      runId, args.symbol, args.timeframe, ENGINE_VERSION,
      JSON.stringify({ every: args.every, maxBars: args.maxBars, window: WINDOW, note: "no spread/slippage/costs; both-touch = conservative loss" }),
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
         volume, outcome, both_touch, r_multiple, bars_held, exit_price, score, reason)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)`,
      [
        runId, seq, r.signalTime, r.side, r.entryPrice, r.stopLoss, r.takeProfit,
        r.volume, r.trade.outcome, r.trade.bothTouch, r.trade.rMultiple,
        r.trade.barsHeld, r.trade.exitPrice, r.score, r.reason,
      ],
    );
  }
  await client.end();

  console.log(`[backtest] run ${runId} persisted`);
  console.log(`[backtest] signals=${signalCount} approved=${approvedCount} trades=${metrics.tradeCount}`);
  console.log(`[backtest] winRate=${metrics.winRate}% avgR=${metrics.avgR} expectancy=${metrics.expectancyR}R cumulative=${metrics.cumulativeR}R maxConsecLosses=${metrics.maxConsecutiveLosses} bothTouch=${metrics.bothTouchCount}`);
  console.log("[backtest] HYPOTHESIS ONLY — no costs modeled, engine v0.1");
}

main().catch((err) => {
  console.error("[backtest] failed:", err.message ?? err);
  process.exit(1);
});
