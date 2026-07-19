/**
 * NY AM spread calibration from stored live ticks (Phase 13 — pre-verdict).
 *
 *   npx tsx scripts/calibrate-spread.ts [--symbol XAUUSDm]
 *
 * Computes the observed spread percentiles over NY AM (12:00–16:00 UTC) ticks
 * and prints the final cost-profile numbers per the user's frozen formula
 * (2026-07-18): spreadBase = max(0.26, p95 NY AM) · spreadStress = max(0.30,
 * p99 NY AM). Refuses to output a calibration below the coverage floor of
 * 3 distinct NY AM sessions (target 5) — a single session is weather, not
 * climate. Read-only; calibration uses only cost inputs (spreads), never
 * performance, so it cannot leak anything.
 *
 * The printed values must be persisted LITERALLY (with provenance) into
 * lib/backtest/costs.ts before the verdict run.
 */

import { Client } from "pg";

const CONNECTION =
  process.env.TRADINGOS_DB ??
  "postgres://tradingos:tradingos_dev@localhost:5433/tradingos";

const MIN_SESSIONS = 3;
const TARGET_SESSIONS = 5;
const BASE_FLOOR = 0.26; // current frozen profile (London-proxy observation)
const STRESS_FLOOR = 0.3;

async function main(): Promise<void> {
  const symbol = (() => {
    const i = process.argv.indexOf("--symbol");
    return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : "XAUUSDm";
  })();

  const client = new Client({ connectionString: CONNECTION });
  await client.connect();

  const perSession = await client.query(
    `SELECT ts::date AS day, count(*)::int AS n,
            round(percentile_cont(0.5)  WITHIN GROUP (ORDER BY ask - bid)::numeric, 4) AS p50,
            round(percentile_cont(0.95) WITHIN GROUP (ORDER BY ask - bid)::numeric, 4) AS p95,
            round(percentile_cont(0.99) WITHIN GROUP (ORDER BY ask - bid)::numeric, 4) AS p99,
            round(max(ask - bid)::numeric, 4) AS max
     FROM ticks
     WHERE symbol = $1 AND ts::time >= '12:00' AND ts::time < '16:00'
     GROUP BY ts::date ORDER BY ts::date`,
    [symbol],
  );
  const overall = await client.query(
    `SELECT count(*)::int AS n, min(ts) AS first, max(ts) AS last,
            round(percentile_cont(0.5)  WITHIN GROUP (ORDER BY ask - bid)::numeric, 4) AS p50,
            round(percentile_cont(0.95) WITHIN GROUP (ORDER BY ask - bid)::numeric, 4) AS p95,
            round(percentile_cont(0.99) WITHIN GROUP (ORDER BY ask - bid)::numeric, 4) AS p99
     FROM ticks
     WHERE symbol = $1 AND ts::time >= '12:00' AND ts::time < '16:00'`,
    [symbol],
  );
  await client.end();

  const sessions = perSession.rows;
  console.log(`[calibrate] ${symbol} NY AM (12:00–16:00 UTC) tick coverage: ${sessions.length} distinct sessions`);
  for (const s of sessions) {
    console.log(`  ${String(s.day).slice(0, 10)}  n=${s.n}  p50=${s.p50}  p95=${s.p95}  p99=${s.p99}  max=${s.max}`);
  }

  if (sessions.length < MIN_SESSIONS) {
    console.error(
      `\n[calibrate] INSUFFICIENT COVERAGE: ${sessions.length}/${MIN_SESSIONS} minimum NY AM sessions ` +
      `(target ${TARGET_SESSIONS}). Run the observer 12:00–16:00 UTC on more days, then re-run. ` +
      `No calibration output — do NOT freeze a profile from this.`,
    );
    process.exit(1);
  }
  if (sessions.length < TARGET_SESSIONS) {
    console.warn(`[calibrate] ⚠ coverage ${sessions.length} < target ${TARGET_SESSIONS} sessions — acceptable minimum, more is better.`);
  }

  const o = overall.rows[0];
  const p95 = Number(o.p95);
  const p99 = Number(o.p99);
  const spreadBase = Math.max(BASE_FLOOR, p95);
  const spreadStress = Math.max(STRESS_FLOOR, p99);

  console.log(`\n[calibrate] overall NY AM: n=${o.n} ticks, ${String(o.first)} → ${String(o.last)}`);
  console.log(`[calibrate] p50=${o.p50} p95=${o.p95} p99=${o.p99}`);
  console.log("\n[calibrate] FINAL VALUES (persist literally in lib/backtest/costs.ts, then commit):");
  console.log(`  spreadBase   = max(${BASE_FLOOR}, p95 ${p95}) = ${spreadBase}`);
  console.log(`  spreadStress = max(${STRESS_FLOOR}, p99 ${p99}) = ${spreadStress}`);
  console.log(`  slippageBase = 0.05/leg · slippageStress = 0.10/leg (user-fixed, unchanged)`);
  console.log(
    `  provenance   = "${symbol} NY AM ticks, ${sessions.length} sessions ` +
    `(${String(sessions[0].day).slice(0, 10)} → ${String(sessions.at(-1)!.day).slice(0, 10)}), n=${o.n}, ` +
    `p95=${p95}, p99=${p99}, formula user-fixed 2026-07-18"`,
  );
}

main().catch((err) => {
  console.error("[calibrate] failed:", err.message ?? err);
  process.exit(1);
});
