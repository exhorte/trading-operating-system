import { describe, expect, it } from "vitest";
import type { DiscoveredAccount } from "@/lib/api/generated";
import { accountTypeFor, blockers, followsFtmo, loginOf, registrationFor, reviewOf, type Review, type Wanted } from "./connect";

function found(overrides: Partial<DiscoveredAccount> = {}): DiscoveredAccount {
  return {
    login: 123456789,
    server: "Exness-MT5Trial10",
    company: "Exness Technologies Ltd",
    currency: "USD",
    leverage: 500,
    balance: 10000,
    equity: 10000,
    margin: 0,
    marginFree: 10000,
    marginLevel: null,
    tradeMode: "demo",
    marginMode: "hedging",
    fifoClose: false,
    tradeAllowed: true,
    tradeExpert: true,
    openPositions: 0,
    pendingOrders: 0,
    provider: "EXNESS",
    environment: "DEMO",
    symbolSuffix: "m",
    symbols: [],
    capital: { amount: 10000, source: "first_deposit", at: "2026-10-31T20:00:00Z", reliable: true },
    suggestedName: "Exness 123456789 démo",
    terminalPath: null,
    warnings: [],
    ...overrides,
  };
}

const exness: Wanted = { provider: "EXNESS", rules: "own" };
const ftmoOnExness: Wanted = { provider: "EXNESS", rules: "ftmo" };
const ftmo: Wanted = { provider: "FTMO", rules: "own" };
const confirmed = (overrides: Partial<Review> = {}): Review => ({ ...reviewOf(found()), capitalConfirmed: true, ...overrides });

describe("reviewOf", () => {
  it("starts from the broker's own figures, with the capital still to be confirmed", () => {
    expect(reviewOf(found())).toEqual({ name: "Exness 123456789 démo", capital: "10000", capitalConfirmed: false, environment: "DEMO" });
  });

  it("falls back to a demo when the broker's mode is unknown — and the trader can change it", () => {
    expect(reviewOf(found({ environment: null })).environment).toBe("DEMO");
  });
});

describe("which rules an account follows", () => {
  it("is FTMO's for a FTMO account, and for a demo that rehearses them", () => {
    expect(followsFtmo(ftmo)).toBe(true);
    expect(followsFtmo(ftmoOnExness)).toBe(true);
    expect(followsFtmo(exness)).toBe(false);
    expect([accountTypeFor(exness), accountTypeFor(ftmoOnExness), accountTypeFor(ftmo)]).toEqual(["DIRECT", "PROP_CHALLENGE", "PROP_CHALLENGE"]);
  });
});

describe("blockers", () => {
  it("lets a confirmed, consistent reading through", () => {
    expect(blockers(found(), exness, confirmed())).toEqual([]);
    expect(blockers(found(), ftmoOnExness, confirmed())).toEqual([]);
  });

  it("will not take the capital without the trader's confirmation", () => {
    expect(blockers(found(), exness, { ...confirmed(), capitalConfirmed: false })).toEqual([
      expect.stringContaining("Confirme le capital initial"),
    ]);
  });

  it("notices a server that belongs to another provider than the one chosen", () => {
    expect(blockers(found(), ftmo, confirmed())).toEqual([expect.stringContaining("est celui de Exness, pas de FTMO")]);
  });

  it("accepts a server it does not recognise: the trader chose the provider", () => {
    expect(blockers(found({ provider: null }), exness, confirmed())).toEqual([]);
  });

  it("refuses the FTMO profile on anything but a demo", () => {
    expect(blockers(found({ environment: "LIVE" }), ftmoOnExness, confirmed({ environment: "LIVE" }))).toEqual([
      expect.stringContaining("ne se répète que sur un compte démo"),
    ]);
    expect(blockers(found(), ftmoOnExness, confirmed({ environment: "SIMULATED" }))).toHaveLength(1);
  });

  it.each(["", "abc", "0", "-5", "100000001"])("refuses the capital %j for a direct account", (capital) => {
    expect(blockers(found(), exness, confirmed({ capital })).length).toBeGreaterThan(0);
  });

  it("holds a challenge to FTMO's sizes", () => {
    expect(blockers(found(), ftmoOnExness, confirmed({ capital: "999" })).length).toBeGreaterThan(0);
    expect(blockers(found(), ftmoOnExness, confirmed({ capital: "10 000,50" }))).toEqual([]);
  });

  it("wants a name of 1 to 80 characters", () => {
    expect(blockers(found(), exness, confirmed({ name: "  " })).length).toBeGreaterThan(0);
    expect(blockers(found(), exness, confirmed({ name: "x".repeat(81) })).length).toBeGreaterThan(0);
  });
});

describe("registrationFor", () => {
  it("registers a direct account with its capital as the reference", () => {
    expect(registrationFor(found(), exness, confirmed({ name: "  Démo  " }))).toEqual({
      name: "Démo",
      provider: "EXNESS",
      accountType: "DIRECT",
      login: 123456789,
      server: "Exness-MT5Trial10",
      currency: "USD",
      environment: "DEMO",
      terminalPath: null,
      symbolSuffix: "m",
      referenceBalance: 10000,
      rulesProfile: null,
    });
  });

  it("registers an Exness demo that rehearses FTMO's rules: Exness broker, FTMO challenge sized on the capital", () => {
    const request = registrationFor(found(), ftmoOnExness, confirmed());
    expect(request).toMatchObject({
      provider: "EXNESS",
      accountType: "PROP_CHALLENGE",
      symbolSuffix: "m",
      challenge: { type: "2-step", accountSize: 10000, phase: "challenge" },
      rulesProfile: "FTMO",
    });
    expect(request).not.toHaveProperty("referenceBalance");
  });

  it("registers a real FTMO account as FTMO, without any rehearsal", () => {
    const request = registrationFor(found({ provider: "FTMO", server: "FTMO-Server3", symbolSuffix: "" }), ftmo, confirmed());
    expect(request).toMatchObject({ provider: "FTMO", accountType: "PROP_CHALLENGE", symbolSuffix: "", rulesProfile: null });
  });

  it("never carries a password", () => {
    expect(JSON.stringify(registrationFor(found(), exness, confirmed()))).not.toMatch(/password/i);
  });
});

describe("loginOf", () => {
  it.each([
    ["123456789", 123456789],
    [" 123 456 789 ", 123456789],
    ["0", null],
    ["-3", null],
    ["12.5", null],
    ["abc", null],
    ["", null],
  ])("reads %j as %j", (text, expected) => {
    expect(loginOf(text)).toBe(expected);
  });
});
