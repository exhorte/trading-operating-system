import { describe, expect, it } from "vitest";
import type { EffectiveLimit, ProviderLossState } from "@/lib/api/generated";
import {
  confidenceView,
  limitProvenance,
  limitValue,
  lossLines,
  lossStatusLabel,
  lossTone,
  modeLabel,
  money,
  reasonText,
  sourceLabel,
} from "./provider-view";

function limit(overrides: Partial<EffectiveLimit> = {}): EffectiveLimit {
  return {
    key: "daily_loss_percent",
    label: "Daily loss",
    unit: "percent",
    candidates: [
      { source: "personal", value: 5, origin: "the trader's rules" },
      { source: "product", value: 3, origin: "FTMO Challenge 1-Step, rules of 2026-11-02" },
    ],
    value: 3,
    bindingSource: "product",
    bindingOrigin: "FTMO Challenge 1-Step, rules of 2026-11-02",
    enforcedBy: "gate-daily-loss, provider loss floor",
    detail: "",
    ...overrides,
  };
}

function loss(overrides: Partial<ProviderLossState> = {}): ProviderLossState {
  return {
    status: "ok",
    ruleSetId: "FTMO_CHALLENGE_2STEP@2026-11-02",
    ruleVersion: "2026-11-02",
    timezone: "Europe/Prague",
    initialCapital: 100000,
    equity: 99000,
    dailyReferenceBalance: 100000,
    dailyReferenceAt: "2026-11-02T23:00:00Z",
    dailyLossAmount: 5000,
    dailyFloor: 95000,
    dailyRemaining: 4000,
    maxMethod: "static_initial",
    maxReferenceBalance: 100000,
    maxLossAmount: 10000,
    maxFloor: 90000,
    maxRemaining: 9000,
    floatingPl: null,
    realizedPl: null,
    commissions: null,
    swaps: null,
    reasons: [],
    detail: "",
    ...overrides,
  };
}

describe("a refusal is a sentence, never a bare code", () => {
  it("words each stable code the core can send", () => {
    expect(reasonText("account_product_unknown")).toMatch(/déclare-le/);
    expect(reasonText("provider_daily_reference_missing")).toMatch(/aucune entrée/);
    expect(reasonText("provider_news_calendar_unknown")).toMatch(/refusées par prudence/);
  });

  it("shows a code it does not know as the code itself", () => {
    expect(reasonText("something_new")).toBe("something_new");
  });
});

describe("limits", () => {
  it("shows the value with its unit, and a dash when nothing bounds it", () => {
    expect(limitValue(limit())).toBe("3 %");
    expect(limitValue(limit({ unit: "count", value: 15 }))).toBe("15");
    expect(limitValue(limit({ unit: "lots", value: 0.5 }))).toBe("0.5 lot");
    expect(limitValue(limit({ value: null }))).toBe("—");
  });

  it("says who binds a limit and what the other sources said", () => {
    expect(limitProvenance(limit())).toBe(
      "Produit — FTMO Challenge 1-Step, rules of 2026-11-02 · aussi : tes règles 5 %",
    );
  });

  it("says when no source bounds a limit", () => {
    expect(limitProvenance(limit({ candidates: [], value: null, bindingSource: null, bindingOrigin: null }))).toBe(
      "aucune source ne la borne",
    );
  });

  it("names every source", () => {
    expect(sourceLabel("personal")).toBe("Tes règles");
    expect(sourceLabel("account")).toBe("État du compte");
  });
});

describe("identification", () => {
  it("puts the confidence in words and a tone", () => {
    expect(confidenceView("CONFIRMED")).toEqual({ label: "Confirmé", tone: "profit" });
    expect(confidenceView("CONFLICT").tone).toBe("loss");
  });

  it("names the account mode, and FTMO as simulated", () => {
    expect(modeLabel("SIMULATED")).toMatch(/fonds fictifs/);
    expect(modeLabel(null)).toBe("inconnu");
  });
});

describe("the provider's floors", () => {
  it("lists the two floors with their reference, their floor and the margin left", () => {
    const [daily, maximum] = lossLines(loss(), "USD");
    expect(daily.label).toBe("Perte quotidienne (Europe/Prague, 00:00)");
    expect(daily.floor).toMatch(/95[\s  ]000,00 USD/);
    expect(maximum.label).toBe("Perte maximale (statique)");
    expect(maximum.margin).toMatch(/9[\s  ]000,00 USD/);
  });

  it("calls the trailing maximum by its name", () => {
    const [, maximum] = lossLines(loss({ maxMethod: "trailing_eod_balance" }), "USD");
    expect(maximum.label).toBe("Perte maximale (glissante, fin de journée)");
  });

  it("shows a figure the core could not establish as unknown, never as zero", () => {
    const [daily] = lossLines(loss({ status: "unknown", dailyReferenceBalance: null, dailyFloor: null, dailyRemaining: null }), "USD");
    expect(daily.reference).toBe("inconnu");
    expect(daily.floor).toBe("inconnu");
    expect(money(null, "USD")).toBe("inconnu");
  });

  it("has no line for a product that imposes no floor", () => {
    expect(lossLines(loss({ status: "not_applicable" }), "USD")).toEqual([]);
  });

  it("reads the status as a tone and a sentence", () => {
    expect(lossTone(loss({ status: "breached" }))).toBe("loss");
    expect(lossTone(loss({ status: "unknown" }))).toBe("warning");
    expect(lossTone(loss())).toBe("profit");
    expect(lossStatusLabel(loss({ status: "unknown" }))).toMatch(/entrées refusées/);
  });
});
