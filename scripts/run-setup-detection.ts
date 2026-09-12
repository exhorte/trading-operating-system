/**
 * EA-02 worker — reads the M1 JSONL/spread snapshots that
 * tools/mt5-observer/export_m1_candles.py writes, upserts the candles into
 * TimescaleDB (same table, same upsert shape as scripts/import-candles.ts),
 * aggregates H1/H4/D1 in TS (lib/analysis/aggregate.ts), evaluates the five
 * S01 pre-conditions directly against Postgres, and — only if they all
 * pass — runs lib/setup/proposal.ts::evaluateSetup, persisting the outcome
 * to setup_proposals. Runs in a loop; no network beyond the DB connection,
 * no order of any kind, no import from lib/execution/.
 *
 *   npx tsx scripts/run-setup-detection.ts
 *
 * Env: TRADINGOS_DB (connection string), TRADINGOS_ACCOUNT_ID (single
 * account — see EA-02-observe-taux-accord.md; multi-account is EA-04+),
 * TRADINGOS_CANDLES_DIR (defaults to tools/mt5-observer).
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Client } from "pg";
import { aggregateCandles } from "@/lib/analysis/aggregate";
import { DEFAULT_SESSION_WINDOWS } from "@/lib/analysis/config";
import { defaultRiskPolicy } from "@/lib/risk/policy";
import { isNewsBlackout, type UpcomingRelease } from "@/lib/risk/news-calendar";
import { isInKillzone, isPastNyLunch } from "@/lib/setup/preconditions";
import { evaluateSetup, type SetupProposalInput } from "@/lib/setup/proposal";
import type { Candle, SessionWindow } from "@/lib/domain/market";
import type { Timeframe, UtcTimestamp } from "@/lib/domain/primitives";
import type { SetupOutcome } from "@/lib/domain/setup";

const CONNECTION = process.env.TRADINGOS_DB ?? "postgres://tradingos:tradingos_dev@localhost:5433/tradingos";
const ACCOUNT_ID = process.env.TRADINGOS_ACCOUNT_ID ?? "unknown";
const CANDLES_DIR = process.env.TRADINGOS_CANDLES_DIR ?? join(__dirname, "..", "tools", "mt5-observer");
const INTERVAL_MS = 60_000;
const REACTION_WINDOW_M1_BARS = 30;

// Provisional, FX-scale defaults for EURUSD/GBPUSD (5-digit quotes) — NOT
// DEFAULT_ANALYSIS_CONFIG's values, which are tuned for XAUUSD's ~4000
// price scale (e.g. equalLevelTolerance 0.3 would be 3000 pips on EURUSD).
// Posed, not derived — same status as S01's cost threshold, to revisit
// once EA-04's symbol registry and an observation sample exist.
const FX_DETECTION_CONFIG = {
  swingLookback: 2,
  equalLevelTolerance: 0.0003, // 3 pips
  minFvgSize: 0.0001, // 1 pip
  atrPeriod: 14,
  minBodyAtrMultiple: 1.5, // S01, step 5 — given, not guessed
  spreadBuffer: 0.0001, // 1 pip
  costThreshold: 0.25, // S01, "porte de coût" — given
  minRiskReward: 3, // S01, "porte R:R" — given
};

const SYMBOLS = [
  { canonical: "EURUSD", jsonlName: "m1_eurusd.jsonl", spreadName: "spread_eurusd.json" },
  { canonical: "GBPUSD", jsonlName: "m1_gbpusd.jsonl", spreadName: "spread_gbpusd.json" },
];

interface JsonCandle {
  symbol: string;
  timeframe: string;
  openTime: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  closed: boolean;
}

interface SpreadSnapshot {
  symbol: string;
  bid: number;
  ask: number;
  spread: number;
  point: number;
  timestamp: number;
}

function readJsonl(path: string): JsonCandle[] {
  const text = readFileSync(path, "utf-8");
  return text
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .map((line) => JSON.parse(line) as JsonCandle);
}

function readSpread(path: string): SpreadSnapshot | null {
  try {
    return JSON.parse(readFileSync(path, "utf-8")) as SpreadSnapshot;
  } catch {
    return null; // not yet written, or the export loop hasn't run this cycle
  }
}

function toCandle(j: JsonCandle): Candle {
  return {
    symbol: j.symbol,
    timeframe: j.timeframe as Timeframe,
    openTime: new Date(j.openTime).toISOString(),
    open: j.open,
    high: j.high,
    low: j.low,
    close: j.close,
    volume: j.volume,
    closed: j.closed,
  };
}

/** Same upsert shape as scripts/import-candles.ts — not imported from
 * there (that script is a one-shot CLI, not a module), kept short enough
 * that duplicating it once is cheaper than reshaping a working script. */
async function upsertCandles(client: Client, rows: JsonCandle[]): Promise<void> {
  if (rows.length === 0) {
    return;
  }
  const values: unknown[] = [];
  const tuples = rows.map((c, i) => {
    const o = i * 9;
    values.push(c.symbol, c.timeframe, new Date(c.openTime).toISOString(), c.open, c.high, c.low, c.close, c.volume, c.closed);
    return `($${o + 1},$${o + 2},$${o + 3}::timestamptz,$${o + 4},$${o + 5},$${o + 6},$${o + 7},$${o + 8},$${o + 9})`;
  });
  await client.query(
    `INSERT INTO candles (symbol, timeframe, open_time, open, high, low, close, volume, closed)
     VALUES ${tuples.join(",")}
     ON CONFLICT (symbol, timeframe, open_time) DO UPDATE
       SET open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
           close = EXCLUDED.close, volume = EXCLUDED.volume, closed = EXCLUDED.closed`,
    values,
  );
}

/** Same query as RiskTodayRepository.cs (T02a/T02b) — read directly, not
 * re-derived, per that repository's own doc comment on why. */
async function isLockoutActive(client: Client, accountId: string): Promise<boolean> {
  const { rows } = await client.query(
    `SELECT lockout_id FROM risk_lockouts
     WHERE account_id = $1 AND cleared_at IS NULL AND (until IS NULL OR until > now())
     ORDER BY since DESC LIMIT 1`,
    [accountId],
  );
  return rows.length > 0;
}

async function tradesToday(client: Client, accountId: string): Promise<number> {
  const { rows: anchorRows } = await client.query(
    `SELECT starts_at_utc FROM trading_day_anchors WHERE account_id = $1 ORDER BY starts_at_utc DESC LIMIT 1`,
    [accountId],
  );
  if (anchorRows.length === 0) {
    return 0; // no anchor resolved yet -> can't bound "today", treat as 0 rather than block on an unknown
  }
  const { rows } = await client.query(
    `SELECT count(*)::int AS n FROM position_opens WHERE account_id = $1 AND opened_at >= $2`,
    [accountId, anchorRows[0].starts_at_utc],
  );
  return rows[0].n as number;
}

async function upcomingReleases(client: Client): Promise<UpcomingRelease[]> {
  const { rows } = await client.query(`SELECT release_id, label, scheduled_at FROM news_releases ORDER BY scheduled_at ASC`);
  return rows.map((r) => ({
    releaseId: r.release_id as number,
    label: r.label as string,
    scheduledAt: new Date(r.scheduled_at).toISOString(),
  }));
}

async function recordOutcome(client: Client, symbol: string, eventAt: UtcTimestamp, outcome: SetupOutcome): Promise<void> {
  const p = outcome.status === "proposed" ? outcome.proposal : null;
  await client.query(
    `INSERT INTO setup_proposals
       (symbol, event_at, status, stage, detail, side, swept_level_kind, swept_level_price,
        entry_price, stop_loss, take_profit, cost_ratio, risk_reward_ratio)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
     ON CONFLICT (symbol, event_at) DO UPDATE
       SET status = EXCLUDED.status, stage = EXCLUDED.stage, detail = EXCLUDED.detail,
           side = EXCLUDED.side, swept_level_kind = EXCLUDED.swept_level_kind,
           swept_level_price = EXCLUDED.swept_level_price, entry_price = EXCLUDED.entry_price,
           stop_loss = EXCLUDED.stop_loss, take_profit = EXCLUDED.take_profit,
           cost_ratio = EXCLUDED.cost_ratio, risk_reward_ratio = EXCLUDED.risk_reward_ratio`,
    [
      symbol,
      eventAt,
      outcome.status,
      outcome.status === "blocked" ? outcome.stage : null,
      outcome.status === "blocked" ? outcome.detail : null,
      p?.side ?? null,
      p?.sweptLevelKind ?? null,
      p?.sweptLevelPrice ?? null,
      p?.entryPrice ?? null,
      p?.stopLoss ?? null,
      p?.takeProfit ?? null,
      p?.costRatio ?? null,
      p?.riskRewardRatio ?? null,
    ],
  );
}

async function evaluateSymbol(
  client: Client,
  canonical: string,
  jsonlName: string,
  spreadName: string,
  sessionWindows: SessionWindow[],
): Promise<void> {
  let rawCandles: JsonCandle[];
  try {
    rawCandles = readJsonl(join(CANDLES_DIR, jsonlName));
  } catch {
    console.log(`[detect] ${canonical}: no M1 snapshot yet (${jsonlName})`);
    return;
  }
  if (rawCandles.length === 0) {
    return;
  }
  await upsertCandles(client, rawCandles);

  const m1 = rawCandles.map(toCandle);
  const brokerSymbol = m1[m1.length - 1].symbol;
  const now = m1[m1.length - 1].openTime;

  // Pre-conditions (S01: "si une seule manque, il n'y a pas de recherche").
  // Evaluated here, not inside lib/setup/ — see lib/domain/setup.ts's note
  // on the precondition_* SetupStage values.
  if (!isInKillzone(now)) {
    return recordOutcome(client, brokerSymbol, now, {
      status: "blocked",
      stage: "precondition_session_window",
      detail: "outside the London/NY AM killzone (NY time)",
    });
  }
  if (isPastNyLunch(now)) {
    return recordOutcome(client, brokerSymbol, now, {
      status: "blocked",
      stage: "precondition_ny_lunch",
      detail: "past 12:00 NY, no new positions",
    });
  }
  const releases = await upcomingReleases(client);
  const policy = defaultRiskPolicy(ACCOUNT_ID);
  if (isNewsBlackout(now, releases, policy.newsBlackoutMinutes)) {
    return recordOutcome(client, brokerSymbol, now, {
      status: "blocked",
      stage: "precondition_calendar",
      detail: `within ${policy.newsBlackoutMinutes}min of a whitelisted FRED release`,
    });
  }
  if (await isLockoutActive(client, ACCOUNT_ID)) {
    return recordOutcome(client, brokerSymbol, now, {
      status: "blocked",
      stage: "precondition_lockout",
      detail: "an active T02a/T02b lockout",
    });
  }
  const trades = await tradesToday(client, ACCOUNT_ID);
  if (trades >= policy.maxTradesPerDay) {
    return recordOutcome(client, brokerSymbol, now, {
      status: "blocked",
      stage: "precondition_trades_limit",
      detail: `${trades}/${policy.maxTradesPerDay} trades today`,
    });
  }

  const spread = readSpread(join(CANDLES_DIR, spreadName));
  if (!spread) {
    console.log(`[detect] ${canonical}: no live spread snapshot yet (${spreadName}), skipping this cycle`);
    return;
  }

  const h1 = aggregateCandles(m1, "M1", "H1");
  const h4 = aggregateCandles(m1, "M1", "H4");
  const d1 = aggregateCandles(m1, "M1", "D1");
  const cutoff = Math.max(0, m1.length - REACTION_WINDOW_M1_BARS);

  const input: SetupProposalInput = {
    symbol: brokerSymbol,
    h4Candles: h4,
    d1Candles: d1,
    h1Candles: h1,
    contextCandles: m1.slice(0, cutoff),
    reactionCandles: m1.slice(cutoff),
    sessionWindows,
    spread: spread.spread,
    commission: 0, // no per-account commission model until EA-04's CostModel
    ...FX_DETECTION_CONFIG,
  };

  const outcome = evaluateSetup(input);
  await recordOutcome(client, brokerSymbol, now, outcome);
  console.log(
    `[detect] ${canonical}: ${outcome.status}` +
      (outcome.status === "blocked" ? ` at ${outcome.stage} (${outcome.detail})` : ""),
  );
}

async function main(): Promise<void> {
  const client = new Client({ connectionString: CONNECTION });
  await client.connect();
  console.log(`[detect] connected. Evaluating every ${INTERVAL_MS / 1000}s.`);

  const run = async () => {
    for (const { canonical, jsonlName, spreadName } of SYMBOLS) {
      try {
        await evaluateSymbol(client, canonical, jsonlName, spreadName, DEFAULT_SESSION_WINDOWS);
      } catch (err) {
        console.error(`[detect] ${canonical} failed:`, err);
      }
    }
  };

  await run();
  setInterval(run, INTERVAL_MS);
}

main().catch((err) => {
  console.error("[detect] fatal:", err);
  process.exit(1);
});
