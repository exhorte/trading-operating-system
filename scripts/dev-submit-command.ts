/**
 * I1 (2026-09-26) — dev harness: sends ONE place_order command through the
 * cockpit hub (CockpitHub.SubmitCommand), the same path the cockpit will use,
 * and prints the ack and report that come back. It is how README steps 2
 * and 3 of the execution agent are run without a UI:
 *
 *   npx tsx scripts/dev-submit-command.ts --account <login> --symbol EURUSDm --side buy --volume 0.01 --sl 1.1500 --tp 1.2000
 *
 * Step 2: a valid command → ACCEPTED then SIMULATED (the agent is OBSERVE:
 * no broker order exists). Step 3: an invalid one → REJECTED with its
 * code — a symbol outside InpAllowedSymbolsCsv (SYMBOL_MISMATCH), a volume
 * above InpMaxVolumePerOrder, --sl 0 (STOP_MISSING), a symbol without
 * InpMaxSpreadCsv entry (SPREAD_LIMIT_MISSING), the agent halted (HALTED).
 *
 * Run by the trader, never by Claude against a live agent (.claude/CLAUDE.md).
 * Needs the cockpit token (TRADINGOS_COCKPIT_TOKEN, read from .env, never
 * printed); the hub also requires an allowed Origin, which this script sends
 * as the cockpit's own. It builds a command WITHOUT a Risk Engine decision
 * (riskApprovalId "dev-harness"): fine while the agent is OBSERVE-only, and
 * the reason this script must be retired or gated before arming (I4).
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { HttpTransportType, HubConnectionBuilder, LogLevel } from "@microsoft/signalr";

interface Args {
  account: string;
  symbol: string;
  side: "buy" | "sell";
  volume: number;
  sl: number;
  tp: number;
  hub: string;
  origin: string;
  waitMs: number;
}

function parseArgs(argv: string[]): Args {
  const read = (name: string): string | undefined => {
    const index = argv.indexOf(`--${name}`);
    return index >= 0 ? argv[index + 1] : undefined;
  };
  const account = read("account");
  if (!account) {
    throw new Error("--account <login> is required (the login the agent is on)");
  }
  const side = (read("side") ?? "buy").toLowerCase();
  if (side !== "buy" && side !== "sell") {
    throw new Error("--side must be buy or sell");
  }
  return {
    account,
    symbol: read("symbol") ?? "EURUSDm",
    side,
    volume: Number(read("volume") ?? "0.01"),
    sl: Number(read("sl") ?? "0"),
    tp: Number(read("tp") ?? "0"),
    hub: read("hub") ?? "http://localhost:5080/hub/cockpit",
    origin: read("origin") ?? "http://localhost:3000",
    waitMs: Number(read("wait-ms") ?? "8000"),
  };
}

/** TRADINGOS_COCKPIT_TOKEN from the environment, else from 04_code/.env —
 *  the last line wins, like docker compose. Never printed. */
function cockpitToken(): string {
  if (process.env.TRADINGOS_COCKPIT_TOKEN) {
    return process.env.TRADINGOS_COCKPIT_TOKEN;
  }
  let token: string | undefined;
  try {
    for (const line of readFileSync(join(process.cwd(), ".env"), "utf8").split(/\r?\n/)) {
      const match = /^[ \t]*TRADINGOS_COCKPIT_TOKEN[ \t]*=[ \t]*(\S+)[ \t]*$/.exec(line);
      if (match) {
        token = match[1];
      }
    }
  } catch {
    // no .env: handled below
  }
  if (!token) {
    throw new Error("TRADINGOS_COCKPIT_TOKEN not found (environment or .env) — run scripts/start-live.ps1 first");
  }
  return token;
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  const token = cockpitToken();
  const now = new Date();
  const commandId = `dev-${now.getTime().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

  const connection = new HubConnectionBuilder()
    .withUrl(args.hub, {
      transport: HttpTransportType.WebSockets,
      skipNegotiation: true,
      accessTokenFactory: () => token,
      headers: { Origin: args.origin },
    })
    .configureLogging(LogLevel.Warning)
    .build();

  const seen: string[] = [];
  connection.on("event", (envelope: { type: string; payload: Record<string, unknown> }) => {
    const payload = envelope.payload as { ack?: { commandId?: string }; report?: { commandId?: string } };
    const id = payload.ack?.commandId ?? payload.report?.commandId;
    if (id !== commandId) {
      return;
    }
    seen.push(envelope.type);
    console.log(`${envelope.type}: ${JSON.stringify(payload.ack ?? payload.report)}`);
  });

  await connection.start();
  console.log(`hub connected — sending ${commandId} (${args.side} ${args.volume} ${args.symbol}, sl ${args.sl}, tp ${args.tp}) for account ${args.account}`);

  await connection.invoke("SubmitCommand", {
    kind: "place_order",
    commandId,
    accountId: args.account,
    agentId: "dev-harness",
    protocolVersion: 1,
    riskApprovalId: "dev-harness",
    expiresAt: new Date(now.getTime() + 60_000).toISOString(),
    issuedAt: now.toISOString(),
    symbol: args.symbol,
    side: args.side,
    orderType: "market",
    volume: args.volume,
    limitPrice: null,
    stopLoss: args.sl,
    takeProfit: args.tp,
    signalId: null,
    strategyId: null,
  });

  await new Promise((resolve) => setTimeout(resolve, args.waitMs));
  await connection.stop();
  if (seen.length === 0) {
    console.log("no ack or report came back for this command within the wait — is the agent connected (GET /health → agentConnected)?");
    process.exitCode = 1;
  }
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
