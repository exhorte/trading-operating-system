/**
 * T08 — pure Markdown rendering of WeeklyStats. Kept separate from
 * stats.ts (the numbers) and index.ts (fetching/writing) so the two can
 * change independently — styling the document should never risk touching
 * a computed number.
 */

import type { WeeklyStats } from "./stats.js";

function formatMoney(value: number): string {
  const sign = value >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(value).toFixed(2)}`;
}

function formatDate(iso: string): string {
  return new Date(iso).toISOString().slice(0, 10);
}

const VIOLATION_LABELS: Record<string, string> = {
  LOCKOUT_ACTIVE: "Trade during an active lockout",
  SESSION_WINDOW: "Trade outside the allowed session",
  SIZE_POLICY: "Size exceeded the risk policy",
};

export function renderWeeklyReview(stats: WeeklyStats): string {
  const lines: string[] = [];
  const weekLabel = `${formatDate(stats.weekStartUtc)} to ${formatDate(stats.weekEndUtc)}`;

  lines.push(`# Weekly review — ${weekLabel}`);
  lines.push("");
  lines.push(
    "Facts about the week, not a verdict on the strategy — the KPI is compliance, not P&L " +
      "(charter.md, principe 2). Generated automatically, zero manual entry.",
  );
  lines.push("");

  lines.push("## Statistics");
  lines.push("");
  lines.push(`- Trades closed: **${stats.tradeCount}**`);
  lines.push(`- Net realized P&L: **${formatMoney(stats.netRealizedPnl)}**`);
  if (stats.bySymbol.length > 0) {
    lines.push("- By symbol:");
    for (const s of stats.bySymbol) {
      lines.push(`  - ${s.symbol}: ${s.count} trade(s), ${formatMoney(s.netRealizedPnl)}`);
    }
  }
  lines.push("");

  lines.push("## Compliance");
  lines.push("");
  lines.push(`Weekly compliance rate: **${Math.round(stats.complianceRate * 100)}%**`);
  lines.push("");
  if (stats.topViolationTypes.length === 0) {
    lines.push("No violations detected this week.");
  } else {
    lines.push("Most frequent violations:");
    lines.push("");
    for (const v of stats.topViolationTypes) {
      lines.push(`- ${VIOLATION_LABELS[v.type] ?? v.type}: ${v.count} trade(s)`);
    }
  }
  lines.push("");

  lines.push("## Worst trades");
  lines.push("");
  if (stats.worstTrades.length === 0) {
    lines.push("No closed trades this week.");
  } else {
    for (const t of stats.worstTrades) {
      const capture = t.hasCapture
        ? ` — [capture](http://localhost:3000/journal/${t.brokerPositionId})`
        : "";
      lines.push(
        `- ${formatDate(t.closedAt)} · ${t.symbol} ${t.side.toUpperCase()} · ${formatMoney(t.realizedPnl)}${capture}`,
      );
    }
  }
  lines.push("");

  return lines.join("\n");
}
