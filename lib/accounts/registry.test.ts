import { describe, expect, it } from "vitest";
import { ACCOUNT_PROFILES, resolveAccountProfile, type AccountProfileRegistry } from "./registry";
import { ftmoRiskPolicy, FTMO_COST_MODEL } from "./ftmo";
import type { AccountProfile } from "./types";

function fixtureProfile(accountId: string): AccountProfile {
  return {
    accountId,
    kind: "prop_challenge",
    riskPolicy: ftmoRiskPolicy(accountId, "challenge"),
    costModel: FTMO_COST_MODEL,
    executionProfile: {
      mode: "observe",
      allowedSymbols: ["EURUSD", "GBPUSD"],
      maxVolumePerOrder: 1,
      maxOpenPositions: 3,
      maxSpreadPoints: 40,
    },
    environment: {
      terminal: "MT5-demo-1",
      agentId: "ftmo-agent-1",
      magicNumber: 20260912,
    },
  };
}

describe("resolveAccountProfile", () => {
  it("returns the registered profile for a known account", () => {
    const registry: AccountProfileRegistry = { "ftmo-001": fixtureProfile("ftmo-001") };
    const profile = resolveAccountProfile(registry, "ftmo-001");
    expect(profile).not.toBeNull();
    expect(profile?.kind).toBe("prop_challenge");
  });

  it("returns null for an account not in the registry", () => {
    const registry: AccountProfileRegistry = { "ftmo-001": fixtureProfile("ftmo-001") };
    expect(resolveAccountProfile(registry, "unknown-account")).toBeNull();
  });

  it("the real ACCOUNT_PROFILES registry is empty until an account is confirmed", () => {
    expect(resolveAccountProfile(ACCOUNT_PROFILES, "477029930")).toBeNull();
  });
});
