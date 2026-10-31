import { describe, expect, it, vi } from "vitest";
import { cockpitTokenResponse, fetchCockpitToken, MISSING_TOKEN_MESSAGE } from "./cockpit-token";

describe("cockpitTokenResponse (server side)", () => {
  it("hands the token to a same-origin fetch only", () => {
    expect(cockpitTokenResponse("same-origin", "tok")).toEqual({ status: 200, body: { token: "tok" } });
  });

  it("refuses cross-site, same-site and header-less requests", () => {
    for (const site of ["cross-site", "same-site", "none", null]) {
      const response = cockpitTokenResponse(site, "tok");
      expect(response.status, String(site)).toBe(403);
      expect(JSON.stringify(response.body)).not.toContain("tok\"");
    }
  });

  it("says what to do when .env has no token", () => {
    expect(cockpitTokenResponse("same-origin", undefined)).toEqual({ status: 503, body: { error: MISSING_TOKEN_MESSAGE } });
    expect(cockpitTokenResponse("same-origin", "")).toEqual({ status: 503, body: { error: MISSING_TOKEN_MESSAGE } });
  });
});

describe("fetchCockpitToken (browser side)", () => {
  it("reads the token from the cockpit's own route, never cached", async () => {
    const fetchImpl = vi.fn(async () => Response.json({ token: "tok" }));
    await expect(fetchCockpitToken(fetchImpl as unknown as typeof fetch)).resolves.toBe("tok");
    expect(fetchImpl).toHaveBeenCalledWith("/api/cockpit-token", { cache: "no-store", credentials: "same-origin" });
  });

  it("surfaces the server's explanation", async () => {
    const fetchImpl = vi.fn(async () => Response.json({ error: MISSING_TOKEN_MESSAGE }, { status: 503 }));
    await expect(fetchCockpitToken(fetchImpl as unknown as typeof fetch)).rejects.toThrow(MISSING_TOKEN_MESSAGE);
  });

  it("fails loudly on a network error or an unreadable answer", async () => {
    const down = vi.fn(async () => {
      throw new TypeError("fetch failed");
    });
    await expect(fetchCockpitToken(down as unknown as typeof fetch)).rejects.toThrow(/ne répond pas/);

    const html = vi.fn(async () => new Response("<html>", { status: 500 }));
    await expect(fetchCockpitToken(html as unknown as typeof fetch)).rejects.toThrow("HTTP 500");

    const empty = vi.fn(async () => Response.json({ token: "" }));
    await expect(fetchCockpitToken(empty as unknown as typeof fetch)).rejects.toThrow("HTTP 200");
  });
});
