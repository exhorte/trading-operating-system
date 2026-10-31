import { cockpitTokenResponse } from "@/lib/security/cockpit-token";

/**
 * I0 (2026-09-26): hands the cockpit token (TRADINGOS_COCKPIT_TOKEN, read
 * from .env by `next dev`) to this page's own scripts only — see
 * lib/security/cockpit-token.ts for the guard and its limit. Route handlers
 * are not cached (Next 16), and this one reads request headers anyway.
 */
export function GET(request: Request) {
  const { status, body } = cockpitTokenResponse(
    request.headers.get("sec-fetch-site"),
    process.env.TRADINGOS_COCKPIT_TOKEN,
  );
  return Response.json(body, { status, headers: { "Cache-Control": "no-store" } });
}
