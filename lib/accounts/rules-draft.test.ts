import { describe, expect, it } from "vitest";
import { account } from "@/lib/realtime/test-fixtures";
import {
  applyDraft,
  describeChange,
  draftOf,
  editableFields,
  FIELDS,
  formatField,
  FIELDS_BY_ID,
  isUnchanged,
  withConfigured,
  type Draft,
} from "./rules-draft";

const base = account();
const rules = { riskProfile: base.riskProfile, tradingRules: base.tradingRules, executionProfile: base.executionProfile };

function draft(overrides: Partial<Draft> = {}): Draft {
  return { ...draftOf(rules), ...overrides };
}

describe("draftOf / applyDraft", () => {
  it("round-trips: the draft of some rules describes those rules", () => {
    const applied = applyDraft(rules, draftOf(rules));
    expect(applied.errors).toEqual([]);
    expect(applied.rules).toEqual(rules);
    expect(isUnchanged(rules, draftOf(rules))).toBe(true);
  });

  it("writes each field where it lives and nowhere else", () => {
    const applied = applyDraft(
      rules,
      draft({
        referenceBalance: "25000",
        dailyLossLimitPercent: "4",
        weeklyLossLimitPercent: "7,5",
        maxRiskPerTradePercent: "0.25",
        maxTradesPerDay: "4",
        consecutiveLossPauseMinutes: "45",
        blackoutMinutes: "20",
        maxOpenPositions: "2",
        maxVolumePerOrder: "1.5",
        costThreshold: "0.2",
        commandTtlSeconds: "90",
      }),
    );
    expect(applied.errors).toEqual([]);
    const next = applied.rules!;
    expect(next.riskProfile.drawdown).toMatchObject({
      referenceBalance: 25_000,
      dailyLossLimitPercent: 4,
      weeklyLossLimitPercent: 7.5,
      maxDrawdownLimitPercent: 10,
    });
    expect(next.riskProfile).toMatchObject({ maxRiskPerTradePercent: 0.25, maxTradesPerDay: 4, consecutiveLossPauseMinutes: 45 });
    expect(next.riskProfile.news).toMatchObject({ blackoutMinutes: 20, calendarMaxAgeHours: 48 });
    expect(next.riskProfile.positions).toMatchObject({ maxOpenPositions: 2, maxVolumePerOrder: 1.5 });
    expect(next.executionProfile.limits).toMatchObject({ costThreshold: 0.2, commandTtlSeconds: 90 });
    // what the form cannot reach is carried over untouched
    expect(next.executionProfile.maxMode).toBe(rules.executionProfile.maxMode);
    expect(next.tradingRules).toEqual(rules.tradingRules);
    expect(rules.riskProfile.drawdown.referenceBalance).toBe(10_000); // the original is not mutated
  });

  it("offers the weekly loss limit, and no limit per symbol (ADR 0022)", () => {
    const ids: string[] = FIELDS.map((f) => f.id);
    expect(ids).toContain("weeklyLossLimitPercent");
    expect(ids).not.toContain("maxPositionsPerSymbol");
    expect(applyDraft(rules, draft({ weeklyLossLimitPercent: "0" })).errors.join("\n")).toContain(
      "Perte hebdomadaire maximale : supérieur à 0 et 100 au plus.",
    );
    expect(applyDraft(rules, draft({ weeklyLossLimitPercent: "" })).errors.join("\n")).toContain(
      "Perte hebdomadaire maximale : une valeur est requise.",
    );
  });

  it("never carries a raised autonomy ceiling in from the form", () => {
    const raised = { ...rules, executionProfile: { ...rules.executionProfile, maxMode: "ARMED" as const } };
    expect(applyDraft(raised, draftOf(raised)).rules?.executionProfile.maxMode).toBe("ARMED"); // as it was, no more, no less
    expect(FIELDS.map((f) => f.id)).not.toContain("maxMode");
  });

  it("accepts a decimal comma and empty optional fields", () => {
    const applied = applyDraft(rules, draft({ maxRiskPerTradePercent: "0,75", maxVolumePerOrder: "", referenceBalance: "" }));
    expect(applied.rules?.riskProfile.maxRiskPerTradePercent).toBe(0.75);
    expect(applied.rules?.riskProfile.positions.maxVolumePerOrder).toBeNull();
    expect(applied.rules?.riskProfile.drawdown.referenceBalance).toBeNull();
  });

  it("refuses what the core would refuse, and says which field", () => {
    const applied = applyDraft(
      rules,
      draft({
        dailyLossLimitPercent: "0",
        maxRiskPerTradePercent: "abc",
        maxTradesPerDay: "2.5",
        commandTtlSeconds: "3",
        maxConsecutiveLosses: "",
        referenceBalance: "0",
        maxOpenRiskPercent: "101",
      }),
    );
    expect(applied.rules).toBeNull();
    expect(applied.errors).toHaveLength(7);
    expect(applied.errors.join("\n")).toContain("Perte journalière maximale : supérieur à 0 et 100 au plus.");
    expect(applied.errors.join("\n")).toContain("« abc » n'est pas un nombre");
    expect(applied.errors.join("\n")).toContain("Trades par jour : un nombre entier est attendu.");
    expect(applied.errors.join("\n")).toContain("Durée de vie d'une commande : au moins 5 et 600 au plus.");
    expect(applied.errors.join("\n")).toContain("Pertes consécutives : une valeur est requise.");
  });
});

describe("what a challenge account may edit", () => {
  const challenge = {
    ...rules,
    tradingRules: { ...rules.tradingRules, challenge: { type: "2-step" as const, accountSize: 10_000, phase: "challenge" as const } },
  };

  it("does not offer the capital of an FTMO challenge: it is the size of the challenge", () => {
    expect(editableFields(challenge).map((f) => f.id)).not.toContain("referenceBalance");
    expect(editableFields(rules).map((f) => f.id)).toContain("referenceBalance");
    // and a stray value in the draft cannot change it
    const applied = applyDraft(challenge, { ...draftOf(challenge), referenceBalance: "123" });
    expect(applied.rules?.riskProfile.drawdown.referenceBalance).toBe(10_000);
  });
});

describe("isUnchanged / withConfigured", () => {
  it("sees a change, and ignores formatting", () => {
    expect(isUnchanged(rules, draft({ maxTradesPerDay: "4" }))).toBe(false);
    expect(isUnchanged(rules, draft({ maxRiskPerTradePercent: "0.50", dailyLossLimitPercent: " 5 " }))).toBe(true);
  });

  it("marks the limits as written by the user, or not", () => {
    expect(withConfigured(rules, true).riskProfile.configured).toBe(true);
    expect(withConfigured(rules, false).riskProfile.configured).toBe(false);
    expect(withConfigured(rules, true).riskProfile.maxTradesPerDay).toBe(rules.riskProfile.maxTradesPerDay);
  });
});

describe("describeChange", () => {
  it("says nothing when nothing moved", () => {
    expect(describeChange(rules, rules)).toEqual([]);
  });

  it("names each difference with its unit, before and after", () => {
    const next = applyDraft(rules, draft({ maxRiskPerTradePercent: "0.25", maxVolumePerOrder: "2", referenceBalance: "" })).rules!;
    expect(describeChange(rules, next)).toEqual([
      "Capital de référence : 10000 $ → non fixé",
      "Risque par trade : 0.5 % → 0.25 %",
      "Volume maximal par ordre : non fixé → 2 lots",
    ]);
  });

  it("shows what the form cannot edit when something else moved it", () => {
    const raised = { ...rules, executionProfile: { ...rules.executionProfile, maxMode: "ARMED" as const } };
    expect(describeChange(rules, raised)).toEqual(["Plafond d'autonomie : OBSERVE → ARMED"]);
    expect(describeChange(rules, withConfigured(rules, !rules.riskProfile.configured))).toEqual([
      "Limites écrites par toi : oui → non",
    ]);
    const changed = { ...rules, tradingRules: { ...rules.tradingRules, challenge: { type: "1-step" as const, accountSize: 5000, phase: "funded" as const } } };
    expect(describeChange(rules, changed)).toEqual(["Challenge FTMO modifié"]);
  });

  it("formats a value with its unit", () => {
    expect(formatField(FIELDS_BY_ID.dailyLossLimitPercent, 5)).toBe("5 %");
    expect(formatField(FIELDS_BY_ID.weeklyLossLimitPercent, 7.5)).toBe("7.5 %");
    expect(formatField(FIELDS_BY_ID.maxTradesPerDay, 6)).toBe("6");
    expect(formatField(FIELDS_BY_ID.referenceBalance, null)).toBe("non fixé");
  });
});
