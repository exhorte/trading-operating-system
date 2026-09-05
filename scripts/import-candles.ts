/**
 * Bulk-load historical candles (JSONL from tools/mt5-observer/import_history.py)
 * into the TimescaleDB candles hypertable. Idempotent: upsert on
 * (symbol, timeframe, open_time) — safe to re-run.
 *
 *   npx tsx scripts/import-candles.ts candles.jsonl
 */

import { createReadStream } from "node:fs";
import { createInterface } from "node:readline";
import { Client } from "pg";

const CONNECTION =
  process.env.TRADINGOS_DB ??
  "postgres://tradingos:tradingos_dev@localhost:5433/tradingos";
const BATCH = 1_000;

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

async function flush(client: Client, rows: JsonCandle[]): Promise<void> {
  if (rows.length === 0) {
    return;
  }
  const values: unknown[] = [];
  const tuples = rows.map((c, i) => {
    const o = i * 9;
    values.push(
      c.symbol, c.timeframe, new Date(c.openTime).toISOString(),
      c.open, c.high, c.low, c.close, c.volume, c.closed,
    );
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

async function main(): Promise<void> {
  const file = process.argv[2];
  if (!file) {
    console.error("usage: npx tsx scripts/import-candles.ts <candles.jsonl>");
    process.exit(1);
  }

  const client = new Client({ connectionString: CONNECTION });
  await client.connect();

  let total = 0;
  let batch: JsonCandle[] = [];
  const lines = createInterface({ input: createReadStream(file, "utf-8") });
  for await (const line of lines) {
    if (!line.trim()) {
      continue;
    }
    batch.push(JSON.parse(line) as JsonCandle);
    if (batch.length >= BATCH) {
      await flush(client, batch);
      total += batch.length;
      batch = [];
    }
  }
  await flush(client, batch);
  total += batch.length;

  const { rows } = await client.query(
    "SELECT count(*)::int AS n, min(open_time) AS oldest, max(open_time) AS newest FROM candles",
  );
  await client.end();
  console.log(`[import] upserted ${total} candles; table now: ${rows[0].n} rows, ${rows[0].oldest} → ${rows[0].newest}`);
}

main().catch((err) => {
  console.error("[import] failed:", err.message ?? err);
  process.exit(1);
});
