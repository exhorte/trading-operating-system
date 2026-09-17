#!/usr/bin/env node
/**
 * T08 — generates a Markdown weekly review: statistics, compliance rate,
 * most frequent violations, worst trades. On demand (fiche Décision 2) —
 * no scheduling exists in this repo, "npm run weekly-review" is the
 * trigger, not an automatic Friday evening. Reuses tools/shared and
 * lib/compliance/ exactly as T15 does — no second implementation.
 */

import { writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { fetchJson, requiredAccountId } from "../shared/backend-client.js";
import type { LockoutWindow } from "@/lib/compliance/violations";
import { computeWeeklyStats, type JournalTrade } from "./stats.js";
import { renderWeeklyReview } from "./render.js";

const OUTPUT_DIR = join(process.cwd(), "weekly-reviews");

function parseArgs(argv: string[]): { fromUtc: string; toUtc: string } {
  const fromArg = argv.find((a) => a.startsWith("--from="))?.split("=")[1];
  const toArg = argv.find((a) => a.startsWith("--to="))?.split("=")[1];

  const to = toArg ? new Date(toArg) : new Date();
  const from = fromArg ? new Date(fromArg) : new Date(to.getTime() - 7 * 24 * 60 * 60 * 1000);

  return { fromUtc: from.toISOString(), toUtc: to.toISOString() };
}

async function main() {
  const accountId = requiredAccountId();
  const { fromUtc, toUtc } = parseArgs(process.argv.slice(2));

  const [trades, lockouts] = await Promise.all([
    fetchJson<JournalTrade[]>("/api/journal/trades", {
      accountId,
      from: fromUtc.slice(0, 10),
      to: toUtc.slice(0, 10),
    }),
    fetchJson<LockoutWindow[]>("/api/risk/lockouts", { accountId, to: toUtc }),
  ]);

  const stats = computeWeeklyStats(accountId, fromUtc, toUtc, trades, lockouts);

  // Increment 1's own verification step, kept permanently: numbers on
  // stderr every run, so a generated file's contents are never the only
  // place to check them against the database by hand.
  console.error("Weekly review computed:");
  console.error(JSON.stringify(stats, null, 2));

  const markdown = renderWeeklyReview(stats);
  mkdirSync(OUTPUT_DIR, { recursive: true });
  const filename = `${toUtc.slice(0, 10)}.md`;
  const outputPath = join(OUTPUT_DIR, filename);
  writeFileSync(outputPath, markdown, "utf-8");

  console.error(`Written to ${outputPath}`);
}

main().catch((err) => {
  console.error("Weekly review generation failed:", err);
  process.exit(1);
});
