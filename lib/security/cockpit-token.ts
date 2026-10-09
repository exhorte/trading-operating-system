/**
 * The cockpit token — what the browser presents to the core on every request and every WebSocket
 * (python/trading_os/api/security.py). It lives in the gitignored `.env` (TRADINGOS_COCKPIT_TOKEN, written once by
 * scripts/start.ps1), which both the core and `next dev` read.
 *
 * Two halves: the server side (`cockpitTokenResponse`, behind app/api/cockpit-token) hands it only to this page's own
 * scripts; the browser side (`fetchCockpitToken`) asks for it on every connection attempt and every request, so a token
 * changed in .env is picked up without reloading the tab.
 *
 * Limit: `Sec-Fetch-Site` and the Host check (proxy.ts) stop browsers — the realistic threat, a web page open in another
 * tab. A client that forges both headers can read the token, like any process running as the trader; written down in
 * api/security.py and context/security.
 */

export type CockpitTokenBody = { token: string } | { error: string };

export interface CockpitTokenResponse {
  status: number;
  body: CockpitTokenBody;
}

/** Raised by `fetchCockpitToken` — the clients tell it apart from a core that is simply down. */
export class CockpitTokenError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CockpitTokenError";
  }
}

export const MISSING_TOKEN_MESSAGE =
  "Jeton du cockpit absent : TRADINGOS_COCKPIT_TOKEN manque dans 04_code/.env. " +
  "Lance scripts/start.ps1 (il le crée), puis relance le cockpit.";

/** Server side: only a same-origin fetch from the cockpit's own page. */
export function cockpitTokenResponse(
  secFetchSite: string | null,
  configuredToken: string | undefined,
): CockpitTokenResponse {
  if (secFetchSite !== "same-origin") {
    return { status: 403, body: { error: "same-origin requests only" } };
  }
  if (!configuredToken) {
    return { status: 503, body: { error: MISSING_TOKEN_MESSAGE } };
  }
  return { status: 200, body: { token: configuredToken } };
}

/** Browser side. Throws an Error whose message can be shown as is. */
export async function fetchCockpitToken(fetchImpl: typeof fetch = fetch): Promise<string> {
  let res: Response;
  try {
    res = await fetchImpl("/api/cockpit-token", { cache: "no-store", credentials: "same-origin" });
  } catch {
    throw new CockpitTokenError("Jeton du cockpit illisible : le serveur du cockpit ne répond pas.");
  }
  let body: { token?: unknown; error?: unknown } | null = null;
  try {
    body = (await res.json()) as { token?: unknown; error?: unknown };
  } catch {
    // Not JSON — the status line is all there is.
  }
  if (res.ok && typeof body?.token === "string" && body.token !== "") {
    return body.token;
  }
  throw new CockpitTokenError(
    typeof body?.error === "string" ? body.error : `Jeton du cockpit refusé (HTTP ${res.status}).`,
  );
}

/** Whether `error` came from `fetchCockpitToken` (by name too: an error
 *  that crossed a bundle boundary may fail `instanceof`). */
export function isCockpitTokenError(error: unknown): error is Error {
  return error instanceof CockpitTokenError || (error instanceof Error && error.name === "CockpitTokenError");
}
