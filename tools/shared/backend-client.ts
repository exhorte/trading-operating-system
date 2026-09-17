/**
 * Thin HTTP client over the existing TradingOs.Host REST API, shared by the
 * standalone tsx scripts under tools/ (T15's MCP server, T08's weekly
 * review) that need to read backend data without a browser. Not lib/:
 * requiredAccountId() reads a plain (non-NEXT_PUBLIC_) env var, so it would
 * silently resolve to undefined if ever imported into browser-rendered
 * code — this file is standalone-script-only by construction, never a
 * candidate for reuse from app/ or components/.
 *
 * backendHttpBase() itself IS the same function the cockpit uses
 * (lib/realtime/backend-url.ts) — nothing browser-specific in it (plain
 * process.env + string manipulation), so it works unchanged here.
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

/** Configured once per environment — never asked per call (« usage
 *  strictement personnel », charter.md). Every standalone script under
 *  tools/ that needs an accountId reads it from here, not its own copy. */
export function requiredAccountId(): string {
  const accountId = process.env.TRADING_OS_ACCOUNT_ID;
  if (!accountId) {
    throw new Error(
      "TRADING_OS_ACCOUNT_ID is not set. Configure it in this script's environment.",
    );
  }
  return accountId;
}
