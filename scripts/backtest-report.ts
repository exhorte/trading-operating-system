/**
 * Segmented diagnostic report for a backtest run (Phase 12, ADR 0013).
 *
 *   npx tsx scripts/backtest-report.ts <runId> [--unlock-oos]
 *
 * Prints per-dimension tables (worst buckets first) for the TRAIN and
 * VALIDATION splits, plus the rejection breakdown, and writes the same
 * content to backtest-reports/<runId>.md (gitignored artifact).
 *
 * OUT-OF-SAMPLE IS LOCKED BY DEFAULT: refinement decisions are made on train
 * and confirmed on validation. Pass --unlock-oos ONCE, at the very end of the
 * refinement campaign — reading it earlier turns it into a second validation
 * set and the protection is gone.
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { Client } from "pg";
import {
  DIMENSIONS,
  MULTI_DIMENSIONS,
  reportableTrades,
  segmentBy,
  segmentByMulti,
  summarize,
  type DiagTrade,
  type SegmentStat,
} from "@/lib/backtest/segments";

const CONNECTION =
  process.env.TRADINGOS_DB ??
  "postgres://tradingos:tradingos_dev@localhost:5433/tradingos";

function table(stats: SegmentStat[]): string {
  const lines = [
    "| bucket | n | win% | exp R | cum R | |",
    "| --- | ---: | ---: | ---: | ---: | --- |",
  ];
  for (const s of stats) {
    lines.push(
      `| ${s.bucket} | ${s.n} | ${s.winRate} | ${s.expectancyR} | ${s.cumulativeR} | ${s.lowSample ? "⚠ low n" : ""} |`,
    );
  }
  return lines.join("\n");
}

async function main(): Promise<void> {
  const runId = process.argv[2];
  const unlockOos = process.argv.includes("--unlock-oos");
  if (!runId) {
    console.error("usage: npx tsx scripts/backtest-report.ts <runId> [--unlock-oos]");
    process.exit(1);
  }

  const client = new Client({ connectionString: CONNECTION });
  await client.connect();

  const run = (await client.query("SELECT * FROM backtest_runs WHERE run_id = $1", [runId])).rows[0];
  if (!run) {
    console.error(`[report] run ${runId} not found`);
    process.exit(1);
  }
  const tradeRows = await client.query(
    `SELECT signal_time AS "signalTime", side, outcome, both_touch AS "bothTouch",
            r_multiple AS "rMultiple", bars_held AS "barsHeld", score,
            entry_price AS "entryPrice", stop_loss AS "stopLoss", split, features
     FROM backtest_trades WHERE run_id = $1 ORDER BY seq`,
    [runId],
  );
  const rejRows = await client.query(
    `SELECT reason, session, split, count(*)::int AS n
     FROM backtest_rejections WHERE run_id = $1 GROUP BY reason, session, split ORDER BY n DESC`,
    [runId],
  );
  await client.end();

  const trades: DiagTrade[] = tradeRows.rows.map((r) => ({
    ...r,
    signalTime: new Date(r.signalTime).toISOString(),
    features: r.features ?? {},
  }));
  if (trades.length === 0) {
    console.error("[report] no trades in this run");
    process.exit(1);
  }
  const missingFeatures = trades.filter((t) => Object.keys(t.features).length === 0).length;

  const out: string[] = [];
  const emit = (s: string) => out.push(s);

  emit(`# Backtest diagnostic report — ${runId}`);
  emit("");
  emit(`> **Hypothesis testing only** — ${run.engine_version}. No spread/slippage/costs;`);
  emit(`> both-touch = conservative loss. Grades signal quality, never account performance.`);
  emit(`> Multi-comparison warning: 13+ dimensions — act only on strong, explainable,`);
  emit(`> train+validation-consistent effects, never on a single ⚠ low-n bucket.`);
  emit("");
  // Headline is computed from the REPORTABLE trades only. Reading run.win_rate
  // / run.expectancy_r / run.cumulative_r here leaked OOS performance into
  // every locked report (they are whole-period aggregates) — fixed 2026-07-17.
  const reportable = reportableTrades(trades, unlockOos);
  const headline = summarize(unlockOos ? "full period" : "train+validation", reportable);
  const oosCount = trades.filter((t) => t.split === "oos").length;

  emit(`Period ${String(run.from_time).slice(0, 10)} → ${String(run.to_time).slice(0, 10)} · ` +
       `${run.candle_count} candles · ${run.signal_count} signals`);
  emit("");
  emit(`**${headline.bucket}** · ${headline.n} trades · win ${headline.winRate}% · ` +
       `exp ${headline.expectancyR}R · cum ${headline.cumulativeR}R`);
  if (!unlockOos && oosCount > 0) {
    emit("");
    emit(`🔒 ${oosCount} OOS trades reserved — excluded from every figure above. ` +
         `Whole-period aggregates (incl. the \`backtest_runs\` row) stay withheld until \`--unlock-oos\`.`);
  }
  if (missingFeatures > 0) {
    emit("");
    emit(`⚠ ${missingFeatures}/${trades.length} trades have no features (pre-Phase-12 run) — re-run the backtest to enable all dimensions.`);
  }

  emit("");
  emit(`## Rejections (${rejRows.rows.reduce((s, r) => s + r.n, 0)} signals refused)`);
  emit("");
  emit("| reason | session | split | n |");
  emit("| --- | --- | --- | ---: |");
  for (const r of rejRows.rows) {
    emit(`| ${r.reason} | ${r.session} | ${r.split} | ${r.n} |`);
  }

  const splits = unlockOos ? ["train", "validation", "oos"] : ["train", "validation"];
  for (const split of splits) {
    const inSplit = trades.filter((t) => t.split === split);
    emit("");
    emit(`## Split: ${split.toUpperCase()} (${inSplit.length} trades)`);
    if (split === "oos") {
      emit("");
      emit("**⚠ OUT-OF-SAMPLE — read once, at the end. Do not optimize against this.**");
    }
    for (const [name, key] of Object.entries(DIMENSIONS)) {
      emit("");
      emit(`### ${name}`);
      emit("");
      emit(table(segmentBy(inSplit, key)));
    }
    for (const [name, keys] of Object.entries(MULTI_DIMENSIONS)) {
      emit("");
      emit(`### ${name} (multi-label: bucket sums exceed total)`);
      emit("");
      emit(table(segmentByMulti(inSplit, keys)));
    }
  }
  if (!unlockOos) {
    emit("");
    emit("## Split: OOS — 🔒 locked");
    emit("");
    emit(`${trades.filter((t) => t.split === "oos").length} trades reserved. Unlock ONCE at the end with --unlock-oos.`);
  }

  const report = out.join("\n") + "\n";
  console.log(report);
  mkdirSync("backtest-reports", { recursive: true });
  const file = `backtest-reports/${runId}${unlockOos ? ".final" : ""}.md`;
  writeFileSync(file, report, "utf-8");
  console.log(`[report] written to ${file}`);
}

main().catch((err) => {
  console.error("[report] failed:", err.message ?? err);
  process.exit(1);
});
