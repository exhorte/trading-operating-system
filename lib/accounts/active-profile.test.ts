import { describe, expect, it } from "vitest";
import { evaluateRiskState } from "@/lib/risk/evaluate";
import { defaultRiskPolicy } from "@/lib/risk/policy";
import type { RiskEvaluationInput } from "@/lib/risk/types";
import { exnessProfile, ftmoProfile, resolveActiveProfile } from "./active-profile";
import { detectFirm } from "./firm";
import { ACTIVE_FTMO_CHALLENGE } from "./ftmo";
import { DEFAULT_ACCOUNT_SETTINGS, type AccountSettings } from "./settings";

describe("detectFirm", () => {
  it("recognises each firm from its name, whatever the case or surrounding words", () => {
    expect(detectFirm("FTMO-Demo")).toBe("ftmo");
    expect(detectFirm("FTMO Global Markets Ltd")).toBe("ftmo");
    expect(detectFirm("Exness Technologies Ltd")).toBe("exness");
    expect(detectFirm("exness-mt5trial9")).toBe("exness");
  });

  it("recognises nothing it has no rule for", () => {
    expect(detectFirm("override .env.local")).toBeNull();
    expect(detectFirm("MT5")).toBeNull();
    expect(detectFirm("")).toBeNull();
    expect(detectFirm(null)).toBeNull();
  });

  // T12 incrément 2: the text is a setting — the day FTMO's real `company`
  // string turns out not to contain "FTMO", the trader fixes it in Settings.
  it("uses the recognition texts it is given", () => {
    const matchers = { ftmo: "Prop Trading s.r.o.", exness: "exness" };
    expect(detectFirm("FTMO Prop Trading s.r.o.", matchers)).toBe("ftmo");
    expect(detectFirm("FTMO-Demo", matchers)).toBeNull();
  });

  it("ignores an empty recognition text instead of matching every broker", () => {
    expect(detectFirm("Any Broker Ltd", { ftmo: "  ", exness: "exness" })).toBeNull();
  });
});

describe("resolveActiveProfile with the settings in effect (T12 incrément 2)", () => {
  const configured: AccountSettings = {
    ftmo: {
      challenge: { type: "2-step", accountSize: 25_000, phase: "verification" },
      brokerMatch: "ftmo",
    },
    exness: { referenceBalance: 2_500, brokerMatch: "exness" },
  };

  it("measures an FTMO account from the configured challenge size", () => {
    const profile = resolveActiveProfile({ accountId: "acc", broker: "FTMO-Demo" }, configured);
    expect(profile?.referenceBalance).toBe(25_000);
    expect(profile?.label).toBe("FTMO · 2-Step $25,000 · Vérification");
  });

  it("measures an Exness account from the configured reference", () => {
    const profile = resolveActiveProfile({ accountId: "acc", broker: "Exness Technologies Ltd" }, configured);
    expect(profile?.referenceBalance).toBe(2_500);
    expect(profile?.referenceSource).toContain("fixé dans Settings");
  });

  it("recognises the broker with the configured text", () => {
    const renamed = { ...configured, exness: { ...configured.exness, brokerMatch: "exness-mt5" } };
    expect(resolveActiveProfile({ accountId: "acc", broker: "Exness Technologies Ltd" }, renamed)).toBeNull();
    expect(resolveActiveProfile({ accountId: "acc", broker: "Exness-MT5Trial9" }, renamed)?.firm).toBe("exness");
  });

  it("is exactly the pre-incrément-2 behaviour with the default settings", () => {
    const account = { accountId: "acc", broker: "FTMO-Demo" };
    expect(resolveActiveProfile(account, DEFAULT_ACCOUNT_SETTINGS)).toEqual(resolveActiveProfile(account));
  });
});

describe("resolveActiveProfile", () => {
  it("applies the configured FTMO challenge, measured from its size", () => {
    const profile = resolveActiveProfile({ accountId: "acc", broker: "FTMO-Demo" });
    expect(profile?.firm).toBe("ftmo");
    expect(profile?.referenceBalance).toBe(ACTIVE_FTMO_CHALLENGE.accountSize);
    expect(profile?.challenge).toEqual(ACTIVE_FTMO_CHALLENGE);
    expect(profile?.label).toBe("FTMO · 2-Step $10,000 · Challenge");
    expect(profile?.costModel.commissionPerLotRoundTrip).toBe(5);
  });

  // Décision 3 (2026-09-21): the trader chose FTMO's limits for Exness too.
  it("applies 5 %/10 % to a direct Exness account, with no reference until one is set", () => {
    const profile = resolveActiveProfile({ accountId: "acc", broker: "Exness Technologies Ltd" });
    expect(profile?.firm).toBe("exness");
    expect(profile?.riskPolicy.dailyLossLimitPercent).toBe(5);
    expect(profile?.riskPolicy.maxDrawdownLimitPercent).toBe(10);
    expect(profile?.referenceBalance).toBeNull();
    expect(profile?.referenceSource).toContain("non fixée");
    expect(profile?.challenge).toBeNull();
  });

  it("describes a reference once the trader has fixed one", () => {
    const profile = exnessProfile("acc", 5_000);
    expect(profile.referenceBalance).toBe(5_000);
    expect(profile.referenceSource).toContain("$5,000");
  });

  it("returns null for an unknown broker, so callers keep their pre-T12 behaviour", () => {
    expect(resolveActiveProfile({ accountId: "acc", broker: "Some Other Broker" })).toBeNull();
  });

  // Tripwire. Compliance (lib/compliance/summarize.ts) and /journal still
  // read defaultRiskPolicy, not the active profile — correct only because
  // the one field they use, maxRiskPerTradePercent, is identical in every
  // profile. If a profile ever diverges, this fails and those two callers
  // must be wired to resolveActiveProfile at that moment.
  it("keeps risk per trade identical to the default policy in every profile", () => {
    const expected = defaultRiskPolicy("acc").maxRiskPerTradePercent;
    expect(ftmoProfile("acc", ACTIVE_FTMO_CHALLENGE).riskPolicy.maxRiskPerTradePercent).toBe(expected);
    expect(exnessProfile("acc", null).riskPolicy.maxRiskPerTradePercent).toBe(expected);
  });
});

/**
 * The reason T12 exists, on the real risk engine: the reference balance is
 * what makes the FTMO floor hold.
 *
 * 10 000 $ challenge, −600 $ on day 1, cockpit reopened on day 2 at 9 400 $.
 * Before T12 the engine measured overall loss from 9 400 $ (the balance at
 * connection); FTMO measures it from 10 000 $. At 8 990 $ of equity FTMO has
 * closed the account — the pre-T12 engine still read it as 4.4 % used of 10 %.
 */
describe("the FTMO floor, pre- vs post-T12", () => {
  const profile = ftmoProfile("acc", ACTIVE_FTMO_CHALLENGE);
  const dayTwo: RiskEvaluationInput = {
    policy: profile.riskPolicy,
    initialBalance: 9_400,
    dayStartEquity: 9_400,
    equity: 8_990,
    balance: 9_400,
    positions: [],
    tradesToday: 0,
    consecutiveLosses: 0,
    spreadPoints: 20,
    agentConnected: true,
    session: "london",
    sessionTradingEnabled: true,
    upcomingReleases: [],
    now: "2026-01-06T10:00:00.000Z",
  };

  function totalDrawdownGate(input: RiskEvaluationInput) {
    return evaluateRiskState(input).gates.find((g) => g.gateId === "gate-total-dd");
  }

  it("pre-T12: measured from the connection-time balance, the gate stays open below the floor", () => {
    expect(totalDrawdownGate(dayTwo)?.state).toBe("open");
  });

  it("post-T12: measured from the challenge size, the gate blocks once the floor is crossed", () => {
    const fixed = { ...dayTwo, initialBalance: profile.referenceBalance! };
    expect(totalDrawdownGate(fixed)?.state).toBe("blocked");
  });

  it("post-T12: stays open just above the floor", () => {
    const fixed = { ...dayTwo, initialBalance: profile.referenceBalance!, equity: 9_050 };
    expect(totalDrawdownGate(fixed)?.state).toBe("open");
  });
});
