/**
 * The cockpit's only way to ask the core for something: one typed function over the operation table the core generates
 * (`generated.ts`, from its own OpenAPI document). An operation is named, never spelled as a URL: a path that moves in the
 * core is a compile error here, not a 404 in the field.
 *
 *     const accounts = await call("accounts_list");
 *     const rules = await call("accounts_rules", { path: { account_id } });
 *     await call("risk_acknowledge", { path: { lockout_id }, body: { accountId } });
 *
 * Every request — reads too (ADR 0016) — carries the cockpit token as a bearer. Nothing is ever put in a URL but what the
 * operation declares as a path or query parameter; a body is JSON. A refusal is an `ApiError` carrying the core's own
 * `ErrorBody` (a stable `code` to switch on, a `message` to show as is); a core that does not answer is an `ApiError` with
 * status 0 and the sentence the trader needs ("start the core"), never a bare `TypeError: Failed to fetch`.
 */

import { fetchCockpitToken } from "@/lib/security/cockpit-token";
import { OPERATIONS, type ErrorBody, type OperationId, type Operations } from "./generated";

export const DEFAULT_CORE_URL = "http://127.0.0.1:8000";

/** The core's HTTP base. Loopback by default; `NEXT_PUBLIC_CORE_URL` only for a core on another loopback port. */
export function coreBaseUrl(): string {
  return (process.env.NEXT_PUBLIC_CORE_URL ?? DEFAULT_CORE_URL).replace(/\/+$/, "");
}

/** The stream's URL for a given HTTP base: same host, `ws` scheme, `/ws`. The token is added by the socket, per attempt. */
export function webSocketUrl(base: string = coreBaseUrl()): string {
  return `${base.replace(/^http/, "ws")}/ws`;
}

export class ApiError extends Error {
  constructor(
    /** HTTP status; 0 when no answer came at all. */
    readonly status: number,
    /** The core's stable error code (`token_refused`, `disconnect_refused`…), or `http_<status>` / `unreachable`. */
    readonly code: string,
    message: string,
    /** The structure of the refusal (the reasons a disconnect was refused, the fields a body was refused for). */
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** By name too: an error that crossed a bundle boundary may fail `instanceof`. */
export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError || (error instanceof Error && error.name === "ApiError");
}

// ----------------------------------------------------------------------------------------------------- typed arguments

type NoArgs = Record<string, never>;

type PathArgs<K extends OperationId> = [Operations[K]["pathParams"]] extends [NoArgs]
  ? { path?: undefined }
  : { path: Operations[K]["pathParams"] };

type QueryArgs<K extends OperationId> = [Operations[K]["query"]] extends [NoArgs]
  ? { query?: undefined }
  : { query?: Operations[K]["query"] };

type BodyArgs<K extends OperationId> = [Operations[K]["body"]] extends [undefined]
  ? { body?: undefined }
  : undefined extends Operations[K]["body"]
    ? { body?: Operations[K]["body"] }
    : { body: Operations[K]["body"] };

export type CallArgs<K extends OperationId> = PathArgs<K> & QueryArgs<K> & BodyArgs<K> & { signal?: AbortSignal };

/** The arguments are optional exactly when the operation needs none: forgetting a path parameter does not compile. */
type ArgsTuple<K extends OperationId> = Record<never, never> extends CallArgs<K> ? [args?: CallArgs<K>] : [args: CallArgs<K>];

export type Response<K extends OperationId> = Operations[K]["response"];

// ----------------------------------------------------------------------------------------------------- the URL

/** `/api/accounts/{account_id}` + `{account_id: "a/b"}` → `/api/accounts/a%2Fb`; the query skips what is unset. */
export function buildUrl(
  base: string,
  operation: OperationId,
  pathParams?: Record<string, string>,
  query?: Record<string, unknown>,
): string {
  const path = OPERATIONS[operation].path.replace(/\{(\w+)\}/g, (_match, key: string) => {
    const value = pathParams?.[key];
    if (value === undefined) {
      throw new Error(`${operation}: missing path parameter "${key}"`);
    }
    return encodeURIComponent(value);
  });
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null) {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        params.append(key, String(item));
      }
    } else {
      params.append(key, String(value));
    }
  }
  const search = params.toString();
  return `${base}${path}${search ? `?${search}` : ""}`;
}

// ----------------------------------------------------------------------------------------------------- the refusals

function unreachable(base: string): ApiError {
  return new ApiError(
    0,
    "unreachable",
    `Le cœur ne répond pas (${base}). Est-il démarré ? — python -m trading_os serve, ou scripts/start.ps1.`,
  );
}

/** What the core said, whatever shape it came in: its `ErrorBody`, the framework's `{detail}`, or just a status line. */
async function refusal(res: globalThis.Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // Not JSON — the status line is all there is.
  }
  const record = (body !== null && typeof body === "object" ? body : {}) as Partial<ErrorBody> & { detail?: unknown };
  const code = typeof record.code === "string" ? record.code : `http_${res.status}`;
  const message =
    typeof record.message === "string"
      ? record.message
      : typeof record.detail === "string"
        ? record.detail
        : `Le cœur a refusé la demande (HTTP ${res.status}).`;
  const details = record.details !== null && typeof record.details === "object" ? record.details : {};
  return new ApiError(res.status, code, message, details);
}

// ----------------------------------------------------------------------------------------------------- the client

export interface ClientDeps {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
  /** The bearer. Called with `fresh` after the core refused the one it was given: the token may have changed in `.env`. */
  getToken?: (fresh: boolean) => Promise<string>;
}

/** A cache with a way out: the token is fetched once, and again only after the core refuses it. */
export function cachedToken(fetchToken: () => Promise<string> = fetchCockpitToken): (fresh: boolean) => Promise<string> {
  let cached: Promise<string> | null = null;
  return (fresh) => {
    if (fresh || cached === null) {
      cached = fetchToken().catch((error: unknown) => {
        cached = null; // a failure is not remembered
        throw error;
      });
    }
    return cached;
  };
}

export function createClient(deps: ClientDeps = {}) {
  const getToken = deps.getToken ?? cachedToken();

  async function call<K extends OperationId>(operation: K, ...rest: ArgsTuple<K>): Promise<Response<K>> {
    const args = (rest[0] ?? {}) as {
      path?: Record<string, string>;
      query?: Record<string, unknown>;
      body?: unknown;
      signal?: AbortSignal;
    };
    const base = deps.baseUrl ?? coreBaseUrl();
    const doFetch = deps.fetchImpl ?? fetch;
    const { method } = OPERATIONS[operation];
    const url = buildUrl(base, operation, args.path, args.query);

    async function attempt(fresh: boolean): Promise<globalThis.Response> {
      const token = await getToken(fresh);
      const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
      let body: string | undefined;
      if (args.body !== undefined) {
        headers["Content-Type"] = "application/json";
        body = JSON.stringify(args.body);
      }
      try {
        return await doFetch(url, {
          method,
          headers,
          body,
          signal: args.signal,
          cache: "no-store",
          credentials: "omit",
          referrerPolicy: "no-referrer",
        });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          throw error; // the caller gave up: not a core that is down
        }
        throw unreachable(base);
      }
    }

    let res = await attempt(false);
    if (res.status === 403) {
      const probe = await refusal(res.clone());
      if (probe.code === "token_refused") {
        res = await attempt(true); // the token may have changed since this tab loaded it
      }
    }
    if (!res.ok) {
      throw await refusal(res);
    }
    if (res.status === 204) {
      return undefined as Response<K>;
    }
    return (await res.json()) as Response<K>;
  }

  return { call };
}

const shared = createClient();

/** The cockpit's client, on the configured core. */
export const call = shared.call;
