#!/usr/bin/env node
/**
 * T15 — read-only MCP server over the Trading Operating System's own data.
 * Every tool here is a passthrough to an existing TradingOs.Host REST
 * endpoint (fiche Décision 2), or a client-side recombination of two such
 * passthroughs using the SAME pure functions the cockpit uses (Décision 1:
 * this file can import lib/compliance/ directly because it runs as plain
 * Node/TS, not a rewrite in a third language).
 *
 * ADR 0005 (l'IA reste en lecture) applies literally here: no tool in this
 * file writes anything, ever. accountId is read once from
 * TRADING_OS_ACCOUNT_ID (usage strictement personnel, charter.md) — never a
 * tool parameter, never asked per call.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { fetchJson, requiredAccountId } from "../shared/backend-client.js";
import { evaluateTrade, complianceRate, type ComplianceTradeInput } from "@/lib/compliance/evaluate";
import type { LockoutWindow } from "@/lib/compliance/violations";
import { defaultRiskPolicy } from "@/lib/risk/policy";
import { toCanonicalSymbol } from "@/lib/market/symbols/registry";
import { DEFAULT_SESSION_WINDOWS } from "@/lib/analysis/config";
import type { Candle } from "@/lib/domain/market";

/** Shape of GET /api/journal/trades (JournalRepository.GetTradesAsync). */
interface JournalTrade {
  brokerPositionId: string;
  symbol: string;
  side: string;
  volume: number;
  entryPrice: number | null;
  exitPrice: number;
  realizedPnl: number;
  stopLoss: number | null;
  openedAt: string | null;
  closedAt: string;
  hasCapture: boolean;
}

/** Shape of GET /api/setup-proposals (SetupProposalRepository.GetRecentAsync). */
interface SetupProposal {
  symbol: string;
  eventAt: string;
  status: "proposed" | "blocked";
  stage: string | null;
  detail: string | null;
  side: string | null;
  sweptLevelKind: string | null;
  sweptLevelPrice: number | null;
  entryPrice: number | null;
  stopLoss: number | null;
  takeProfit: number | null;
  costRatio: number | null;
  riskRewardRatio: number | null;
}

/** Shape of GET /api/execution/divergence (ExecutionDivergenceRepository). */
interface ExecutionDivergence {
  externalPositions: Array<{
    brokerPositionId: string;
    symbol: string;
    side: string;
    volume: number;
    magicNumber: number;
    knownCommandId: string | null;
    scannedAt: string;
  }>;
  reconciliations: Array<{
    commandId: string;
    outcome: "executed" | "rejected" | "not_found";
    symbol: string | null;
    side: string | null;
    brokerPositionId: string | null;
    filledVolume: number | null;
    averagePrice: number | null;
    attempts: number;
    detail: string;
    reconciledAt: string;
  }>;
}

const server = new McpServer({
  name: "trading-os",
  version: "1.0.0",
});

function textResult(data: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }] };
}

server.registerTool(
  "get_trades",
  {
    title: "Get closed trades",
    description:
      "Closed trades in a date range, with realized P&L, entry/exit, and capture availability. " +
      "Facts only — no expectancy or win-rate computed here (see get_compliance_violations for " +
      "rule violations; anything beyond that is for the asker to reason about from these facts).",
    inputSchema: {
      from: z.string().describe("Start date, YYYY-MM-DD or ISO 8601"),
      to: z.string().describe("End date, YYYY-MM-DD or ISO 8601"),
      symbol: z.string().optional().describe("Filter to one broker symbol, e.g. EURUSDm"),
    },
  },
  async ({ from, to, symbol }) => {
    const accountId = requiredAccountId();
    const trades = await fetchJson<JournalTrade[]>("/api/journal/trades", { accountId, from, to });
    const filtered = symbol ? trades.filter((t) => t.symbol === symbol) : trades;
    return textResult(filtered);
  },
);

server.registerTool(
  "get_lockouts",
  {
    title: "Get lockout history",
    description: "Every risk lockout window (kill switch, daily loss guard, consecutive-loss pause) up to a point in time.",
    inputSchema: {
      to: z.string().describe("Upper bound, ISO 8601"),
    },
  },
  async ({ to }) => {
    const accountId = requiredAccountId();
    const lockouts = await fetchJson<LockoutWindow[]>("/api/risk/lockouts", { accountId, to });
    return textResult(lockouts);
  },
);

server.registerTool(
  "get_candles",
  {
    title: "Get candles",
    description: "OHLC candles for a symbol/timeframe/range, as stored (never a signal or a level — raw price history).",
    inputSchema: {
      symbol: z.string().describe("Broker symbol, e.g. EURUSDm, GBPUSDm, XAUUSDm"),
      timeframe: z.string().describe("e.g. M1, M15"),
      from: z.string().describe("ISO 8601"),
      to: z.string().describe("ISO 8601"),
    },
  },
  async ({ symbol, timeframe, from, to }) => {
    const candles = await fetchJson<Candle[]>("/api/candles", { symbol, timeframe, from, to });
    return textResult(candles);
  },
);

server.registerTool(
  "get_setup_proposals",
  {
    title: "Get EA-02 setup proposals",
    description:
      "S01 sequence evaluations since a given time — both 'proposed' (a candidate setup detected) and " +
      "'blocked' (why one didn't fire). The measurement instrument (ADR 0011), never a signal to act on.",
    inputSchema: {
      since: z.string().describe("ISO 8601"),
    },
  },
  async ({ since }) => {
    const proposals = await fetchJson<SetupProposal[]>("/api/setup-proposals", { since });
    return textResult(proposals);
  },
);

server.registerTool(
  "get_execution_divergence",
  {
    title: "Get execution divergence",
    description:
      "EA-06: positions the terminal reports with a foreign magic number (EXTERNAL_POSITION, attribution " +
      "only — already counted in the local exposure barrier), and any commandId resolved after the fact.",
    inputSchema: {},
  },
  async () => {
    const accountId = requiredAccountId();
    const divergence = await fetchJson<ExecutionDivergence>("/api/execution/divergence", { accountId });
    return textResult(divergence);
  },
);

server.registerTool(
  "get_compliance_violations",
  {
    title: "Get compliance violations",
    description:
      "T07's closed-taxonomy violations (lockout-active, session-window) per closed trade in a range, and the " +
      "resulting compliance rate. Recomputed here from raw facts on every call, never cached or persisted " +
      "(fiche Décision 3) — this is not a pre-baked performance metric, it re-derives the same answer the " +
      "cockpit's ComplianceBadge shows. Size-outside-policy is NOT included: current balance isn't available " +
      "outside the live SignalR stream, so it's silently skipped rather than approximated (fiche Décision 4) — " +
      "the same graceful degradation evaluateTrade already does with balance=null.",
    inputSchema: {
      from: z.string().describe("Start date, YYYY-MM-DD or ISO 8601"),
      to: z.string().describe("End date, YYYY-MM-DD or ISO 8601"),
    },
  },
  async ({ from, to }) => {
    const accountId = requiredAccountId();
    const [trades, lockouts] = await Promise.all([
      fetchJson<JournalTrade[]>("/api/journal/trades", { accountId, from, to }),
      fetchJson<LockoutWindow[]>("/api/risk/lockouts", { accountId, to: new Date(to).toISOString() }),
    ]);

    const policy = defaultRiskPolicy(accountId);
    const perTrade = trades.map((t) => {
      const input: ComplianceTradeInput = {
        brokerPositionId: t.brokerPositionId,
        symbol: toCanonicalSymbol(t.symbol),
        openedAt: t.openedAt,
        volume: t.volume,
        entryPrice: t.entryPrice,
        stopLoss: t.stopLoss,
      };
      // balance: null — size-outside-policy skipped, see tool description.
      const violations = evaluateTrade(input, lockouts, DEFAULT_SESSION_WINDOWS, null, policy);
      return { brokerPositionId: t.brokerPositionId, closedAt: t.closedAt, violations };
    });

    return textResult({
      complianceRate: complianceRate(perTrade.map((t) => t.violations)),
      trades: perTrade,
    });
  },
);

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("Trading OS MCP server running on stdio.");
}

main().catch((err) => {
  console.error("Trading OS MCP server failed to start:", err);
  process.exit(1);
});
