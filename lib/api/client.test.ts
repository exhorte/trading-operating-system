import { describe, expect, it, vi } from "vitest";
import { ApiError, buildUrl, cachedToken, createClient, isApiError, webSocketUrl } from "./client";

const BASE = "http://core.test";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function clientWith(responses: Array<Response | Error>, token = vi.fn(async () => "tok")) {
  const fetchImpl = vi.fn<typeof fetch>(async () => {
    const next = responses.shift();
    if (next === undefined) {
      throw new Error("no response scripted");
    }
    if (next instanceof Error) {
      throw next;
    }
    return next;
  });
  const { call } = createClient({ baseUrl: BASE, fetchImpl, getToken: token });
  return { call, fetchImpl, token };
}

describe("buildUrl", () => {
  it("fills path parameters, encoded", () => {
    expect(buildUrl(BASE, "accounts_get", { account_id: "exness-1" })).toBe(`${BASE}/api/accounts/exness-1`);
    expect(buildUrl(BASE, "market_quote", { symbol: "EUR/USD#" })).toBe(`${BASE}/api/market/EUR%2FUSD%23`);
  });

  it("serialises the query: skips what is unset, repeats arrays, keeps false", () => {
    const url = buildUrl(BASE, "system_events", undefined, {
      limit: 5,
      types: ["a.b", "c.d"],
      accountId: null,
      since: undefined,
    });
    expect(url).toBe(`${BASE}/api/system/events?limit=5&types=a.b&types=c.d`);
    expect(buildUrl(BASE, "accounts_disconnect", { account_id: "x" }, { force: false })).toBe(
      `${BASE}/api/accounts/x/disconnect?force=false`,
    );
  });

  it("refuses a path with a hole in it", () => {
    expect(() => buildUrl(BASE, "accounts_get", {})).toThrow(/missing path parameter "account_id"/);
  });
});

describe("webSocketUrl", () => {
  it("is the same host with the ws scheme", () => {
    expect(webSocketUrl("http://127.0.0.1:8000")).toBe("ws://127.0.0.1:8000/ws");
    expect(webSocketUrl("https://core.test")).toBe("wss://core.test/ws");
  });
});

describe("call", () => {
  it("sends the bearer on a read and returns the parsed body", async () => {
    const { call, fetchImpl } = clientWith([json([{ id: "a" }])]);
    const accounts = await call("accounts_list");
    expect(accounts).toEqual([{ id: "a" }]);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(`${BASE}/api/accounts`);
    expect(init?.method).toBe("GET");
    expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer tok");
    expect(init?.body).toBeUndefined();
    expect(init?.credentials).toBe("omit");
    expect(init?.cache).toBe("no-store");
  });

  it("sends a JSON body with its content type", async () => {
    const { call, fetchImpl } = clientWith([json({ lockoutId: "l1" }, 201)]);
    await call("risk_engage_kill_switch", { body: { accountId: "a1" } });
    const [, init] = fetchImpl.mock.calls[0];
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe('{"accountId":"a1"}');
    expect((init?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("returns nothing for a 204", async () => {
    const { call } = clientWith([new Response(null, { status: 204 })]);
    expect(await call("accounts_archive", { path: { account_id: "a1" } })).toBeUndefined();
  });

  it("turns the core's error body into an ApiError", async () => {
    const { call } = clientWith([
      json({ code: "disconnect_refused", message: "cannot disconnect: open positions", details: { reasons: ["x"] } }, 409),
    ]);
    const error = await call("accounts_disconnect", { path: { account_id: "a1" } }).catch((e: unknown) => e);
    expect(isApiError(error)).toBe(true);
    expect(error).toMatchObject({
      status: 409,
      code: "disconnect_refused",
      message: "cannot disconnect: open positions",
      details: { reasons: ["x"] },
    });
  });

  it("reads the framework's own { detail } and a bare status line too", async () => {
    const { call } = clientWith([json({ detail: "Not Found" }, 404), new Response("boom", { status: 502 })]);
    await expect(call("accounts_list")).rejects.toMatchObject({ status: 404, code: "http_404", message: "Not Found" });
    await expect(call("accounts_list")).rejects.toMatchObject({ status: 502, code: "http_502" });
  });

  it("says the core is not there when nothing answers", async () => {
    const { call } = clientWith([new TypeError("Failed to fetch")]);
    const error = await call("system_health").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 0, code: "unreachable" });
    expect((error as ApiError).message).toContain(BASE);
  });

  it("does not mistake an aborted request for a dead core", async () => {
    const { call } = clientWith([new DOMException("aborted", "AbortError")]);
    await expect(call("system_health")).rejects.toMatchObject({ name: "AbortError" });
  });

  it("asks for a fresh token once when the core refuses the one it has, then retries", async () => {
    const token = vi.fn(async (fresh: boolean) => (fresh ? "new" : "old"));
    const { call, fetchImpl } = clientWith(
      [json({ code: "token_refused", message: "no" }, 403), json({ ok: true })],
      token as never,
    );
    expect(await call("system_status")).toEqual({ ok: true });
    expect(token.mock.calls.map(([fresh]) => fresh)).toEqual([false, true]);
    expect((fetchImpl.mock.calls[1][1]?.headers as Record<string, string>).Authorization).toBe("Bearer new");
  });

  it("does not retry other refusals, nor a second token refusal", async () => {
    const { call, fetchImpl } = clientWith([
      json({ code: "origin_refused", message: "origin" }, 403),
      json({ code: "token_refused", message: "a" }, 403),
      json({ code: "token_refused", message: "b" }, 403),
    ]);
    await expect(call("system_status")).rejects.toMatchObject({ code: "origin_refused" });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await expect(call("system_status")).rejects.toMatchObject({ code: "token_refused", message: "b" });
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it("is typed: what an operation needs is required, what it does not is refused", () => {
    const { call } = clientWith([]);
    // @ts-expect-error — a path parameter is required
    void call("accounts_get").catch(() => undefined);
    // @ts-expect-error — a body is required
    void call("risk_engage_kill_switch").catch(() => undefined);
    // @ts-expect-error — this operation has no path parameters
    void call("accounts_list", { path: { account_id: "x" } }).catch(() => undefined);
    // @ts-expect-error — an unknown operation
    void call("accounts_nope").catch(() => undefined);
    expect(true).toBe(true);
  });
});

describe("cachedToken", () => {
  it("fetches once, again on demand, and forgets a failure", async () => {
    const source = vi
      .fn<() => Promise<string>>()
      .mockResolvedValueOnce("a")
      .mockResolvedValueOnce("b")
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValueOnce("c");
    const token = cachedToken(source);
    expect(await token(false)).toBe("a");
    expect(await token(false)).toBe("a");
    expect(source).toHaveBeenCalledTimes(1);
    expect(await token(true)).toBe("b");
    await expect(token(true)).rejects.toThrow("down");
    expect(await token(false)).toBe("c"); // the failure was not kept
  });
});
