import { describe, expect, it } from "vitest";
import { defaultRiskPolicy } from "./policy";
import { ftmoRiskPolicy, FTMO_COST_MODEL } from "@/lib/accounts/ftmo";
import type { AccountProfile } from "@/lib/accounts/types";
import type { AccountProfileRegistry } from "@/lib/accounts/registry";

describe("defaultRiskPolicy", () => {
  it("falls back to the existing hardcoded policy for an unregistered account", () => {
    const policy = defaultRiskPolicy("some-unregistered-account");
    expect(policy).toMatchObject({
      accountId: "some-unregistered-account",
      dailyLossLimitPercent: 5,
      maxDrawdownLimitPercent: 10,
    });
  });

  it("returns the registered account's own policy — T01/T03/EA-02 callers unaffected by this new param", () => {
    const registeredPolicy = ftmoRiskPolicy("ftmo-001", "challenge");
    const profile: AccountProfile = {
      accountId: "ftmo-001",
      kind: "prop_challenge",
      riskPolicy: { ...registeredPolicy, dailyLossLimitPercent: 4 }, // distinguishable from the fallback
      costModel: FTMO_COST_MODEL,
      executionProfile: {
        mode: "observe",
        allowedSymbols: ["EURUSD"],
        maxVolumePerOrder: 1,
        maxOpenPositions: 3,
        maxSpreadPoints: 40,
      },
      environment: { terminal: "MT5-demo-1", agentId: "ftmo-agent-1", magicNumber: 1 },
    };
    const registry: AccountProfileRegistry = { "ftmo-001": profile };

    const policy = defaultRiskPolicy("ftmo-001", registry);
    expect(policy.dailyLossLimitPercent).toBe(4);

    // A different, unregistered account still gets the untouched fallback.
    expect(defaultRiskPolicy("other-account", registry).dailyLossLimitPercent).toBe(5);
  });
});
