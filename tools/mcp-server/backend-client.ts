/**
 * T15 — thin HTTP client over the existing TradingOs.Host REST API. Every
 * tool in this server is a passthrough to an endpoint the cockpit already
 * calls — no direct Postgres or MT5 access from this process (fiche
 * Décision 2). backendHttpBase() is the same function the cockpit itself
 * uses; nothing browser-specific in it (plain process.env + string
 * manipulation), so it works unchanged in this Node process.
 */

import { backendHttpBase } from "@/lib/realtime/backend-url";

export class BackendUnreachableError extends Error {
  constructor(url: string, cause: unknown) {
    super(`Trading OS backend unreachable at ${url} — is TradingOs.Host running? (${String(cause)})`);
    this.name = "BackendUnreachableError";
  }
}

/** GET {backendHttpBase()}{path}, query params from `params` (undefined
 *  values omitted, not sent as the literal string "undefined"). */
export async function fetchJson<T>(
  path: string,
  params: Record<string, string | undefined> = {},
): Promise<T> {
  const base = backendHttpBase();
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) {
      query.set(key, value);
    }
  }
  const suffix = query.toString();
  const url = `${base}${path}${suffix ? `?${suffix}` : ""}`;

  let res: Response;
  try {
    res = await fetch(url);
  } catch (err) {
    throw new BackendUnreachableError(url, err);
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${path} returned HTTP ${res.status}: ${body}`);
  }
  return (await res.json()) as T;
}

/** Configured once per fiche Décision — never asked per tool call
 *  (« usage strictement personnel », charter.md). */
export function requiredAccountId(): string {
  const accountId = process.env.TRADING_OS_ACCOUNT_ID;
  if (!accountId) {
    throw new Error(
      "TRADING_OS_ACCOUNT_ID is not set. Configure it in this MCP server's environment — see tools/mcp-server/README.md.",
    );
  }
  return accountId;
}
