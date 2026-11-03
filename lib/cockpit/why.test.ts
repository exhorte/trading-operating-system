import { describe, expect, it } from "vitest";
import type { Opportunity, Reason, WhyNoTrade } from "@/lib/api/generated";
import { describeOpportunity, groupReasons, headlineTone, SOURCE_LABEL } from "./why";

function why(changes: Partial<WhyNoTrade> = {}): WhyNoTrade {
  return {
    accountId: "acc",
    mode: "ARMED",
    ceiling: "AUTONOMOUS",
    headline: "nothing blocks a trade: waiting for a setup",
    realOrdersPossible: true,
    reasons: [],
    opportunities: [],
    evaluations: [],
    evaluatedAt: "2026-11-02T15:00:00Z",
    ...changes,
  };
}

const reason = (source: Reason["source"], blocking: boolean, code = "x"): Reason => ({ source, code, detail: code, blocking });

describe("headlineTone", () => {
  it("is muted while a real order cannot leave the core", () => {
    expect(headlineTone(why({ realOrdersPossible: false }))).toBe("muted");
  });

  it("is a warning when only a human confirmation stands in the way (CONFIRM)", () => {
    expect(headlineTone(why({ reasons: [reason("mode", false, "mode_confirm")] }))).toBe("warning");
  });

  it("is positive when nothing at all blocks", () => {
    expect(headlineTone(why())).toBe("profit");
  });
});

describe("groupReasons", () => {
  it("separates the reasons that block a real order from the ones that only inform, keeping the core's order", () => {
    const groups = groupReasons([
      reason("strategy", false, "a"),
      reason("risk", true, "b"),
      reason("mode", true, "c"),
      reason("guardian", false, "d"),
    ]);
    expect(groups.blocking.map((r) => r.code)).toEqual(["b", "c"]);
    expect(groups.informing.map((r) => r.code)).toEqual(["a", "d"]);
  });
});

describe("describeOpportunity", () => {
  const base: Opportunity = {
    strategyId: "S02",
    symbol: "EURUSDm",
    side: "buy",
    entryPrice: 1.1,
    stopLoss: 1.099,
    takeProfit: 1.103,
    riskRewardRatio: 3,
    at: "2026-11-02T14:58:00Z",
  };

  it("says the strategy, the side, the symbol and the levels", () => {
    expect(describeOpportunity(base)).toBe("S02 · Achat EURUSDm — entrée 1.1 · SL 1.099 · TP 1.103 · R:R 3.0");
  });

  it("leaves out a level the core did not give", () => {
    expect(describeOpportunity({ ...base, side: "sell", takeProfit: null, riskRewardRatio: null })).toBe(
      "S02 · Vente EURUSDm — entrée 1.1 · SL 1.099",
    );
    expect(describeOpportunity({ ...base, entryPrice: null, stopLoss: null, takeProfit: null, riskRewardRatio: null })).toBe(
      "S02 · Achat EURUSDm",
    );
  });
});

describe("SOURCE_LABEL", () => {
  it("names every source the core can give", () => {
    expect(Object.keys(SOURCE_LABEL).sort()).toEqual(["guardian", "mode", "readiness", "risk", "strategy"]);
  });
});
