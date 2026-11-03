import { describe, expect, it } from "vitest";
import { account } from "@/lib/realtime/test-fixtures";
import { challengeLabel, formatCapital, profileOf } from "./profile";

const ftmo = account({
  id: "ftmo-1",
  provider: "FTMO",
  accountType: "PROP_CHALLENGE",
  tradingRules: {
    allowedSymbols: null,
    tradingWindows: [],
    challenge: { type: "2-step", accountSize: 10_000, phase: "challenge" },
    minTradingDays: 4,
    profitTargetPercent: 10,
  },
});

describe("profileOf", () => {
  it("reads an FTMO challenge: its label, its reference, the limits in money", () => {
    const profile = profileOf(ftmo, {
      ...ftmo,
      riskProfile: { ...ftmo.riskProfile, drawdown: { dailyLossLimitPercent: 5, weeklyLossLimitPercent: 10, maxDrawdownLimitPercent: 10, referenceBalance: 10_000 } },
    });
    expect(profile.label).toBe("FTMO · 2-Step $10,000 · Challenge");
    expect(profile.referenceSource).toContain("taille du challenge");
    expect(profile.dailyLossAmount).toBe(500);
    expect(profile.floor).toBe(9_000);
    expect(profile.challenge?.phase).toBe("challenge");
  });

  it("reads a direct account with a fixed capital", () => {
    const direct = account();
    const profile = profileOf(direct, direct);
    expect(profile.label).toBe("Exness · compte direct");
    expect(profile.referenceBalance).toBe(10_000);
    expect(profile.referenceSource).toContain("fixé dans Settings");
    expect(profile.floor).toBe(9_000);
  });

  it("says 'not fixed' rather than inventing a floor when there is no reference", () => {
    const direct = account();
    const profile = profileOf(direct, {
      ...direct,
      riskProfile: { ...direct.riskProfile, drawdown: { ...direct.riskProfile.drawdown, referenceBalance: null } },
    });
    expect(profile.referenceBalance).toBeNull();
    expect(profile.referenceSource).toContain("non fixée");
    expect(profile.floor).toBeNull();
    expect(profile.dailyLossAmount).toBeNull();
  });
});

describe("labels", () => {
  it("formats a capital without cents", () => {
    expect(formatCapital(10_000)).toBe("$10,000");
    expect(formatCapital(25_000.5)).toBe("$25,000.50");
  });

  it("names the challenge type and phase", () => {
    expect(challengeLabel({ type: "1-step", accountSize: 100_000, phase: "funded" })).toBe("FTMO · 1-Step $100,000 · Funded");
  });
});
