import { describe, expect, it } from "vitest";
import type { Bucket, GeneralStats, TradingDayStats } from "./breakdowns";
import {
  describeDays,
  describeDuration,
  describeGeneral,
  describeSide,
  describeTradingDays,
} from "./narrative";

function bucket(label: string, trades: number, pnl: number): Bucket {
  return { label, trades, pnl };
}

function stats(overrides: Partial<GeneralStats> = {}): GeneralStats {
  return {
    tradeCount: 40,
    netPnl: 100,
    winRate: 0.5,
    wins: 20,
    losses: 20,
    breakeven: 0,
    avgWin: 20,
    avgLoss: -15,
    maxWin: 50,
    maxLoss: -40,
    rewardRiskRatio: 20 / 15,
    ...overrides,
  };
}

function days(overrides: Partial<TradingDayStats> = {}): TradingDayStats {
  return {
    dayCount: 4,
    avgTradesPerDay: 7.5,
    positiveDays: 0,
    negativeDays: 4,
    flatDays: 0,
    avgPositiveDay: null,
    avgNegativeDay: -250.97,
    bestDay: null,
    worstDay: null,
    ...overrides,
  };
}

/**
 * The rule these sentences exist under (see narrative.ts): they describe the
 * sample and never recommend a change of behaviour. Selecting what to trade
 * from whichever bucket did best is the post-hoc selection that ended the
 * edge research (ADR 0002), so no generated sentence may suggest it.
 */
const ADVICE_PATTERNS = [/tu devrais/i, /concentre-toi/i, /privilégie/i, /évite de trader/i];

describe("narrative", () => {
  it("names the most frequent bucket and, separately, the costliest", () => {
    const text = describeDuration([bucket("< 2 min", 17, -781.68), bucket("2 – 5 min", 10, -900)]);
    expect(text).toContain("< 2 min");
    expect(text).toContain("17 trades");
    expect(text).toContain("Le plus coûteux est 2 – 5 min");
  });

  it("does not repeat the bucket as costliest when it is already the most frequent", () => {
    const text = describeDuration([bucket("< 2 min", 17, -800), bucket("2 – 5 min", 2, -10)]);
    expect(text).not.toContain("Le plus coûteux");
  });

  it("says so plainly when a dimension has no usable data", () => {
    expect(describeDuration([])).toContain("Aucune donnée exploitable");
  });

  it("flags when opening-day and closing-day readings disagree", () => {
    const agreeing = describeDays([bucket("Lundi", 3, 10)], [bucket("Lundi", 3, 10)]);
    expect(agreeing).toContain("ne traversent pas minuit");

    const diverging = describeDays([bucket("Lundi", 3, 10)], [bucket("Mardi", 3, 10)]);
    expect(diverging).toContain("divergent");
  });

  it("states there is nothing to compare when only one side was traded", () => {
    const text = describeSide([bucket("Vente", 30, -1003.88)]);
    expect(text).toContain("Uniquement des ventes");
    expect(text).toContain("rien à comparer");
  });

  it("warns that a short sample proves nothing", () => {
    expect(describeGeneral(stats({ tradeCount: 12 }))).toContain("Échantillon trop court");
    expect(describeGeneral(stats({ tradeCount: 40 }))).not.toContain("Échantillon trop court");
  });

  it("reports an empty period instead of rendering zeros as a result", () => {
    expect(describeGeneral(stats({ tradeCount: 0 }))).toBe(
      "Aucun trade clôturé sur la période retenue.",
    );
    expect(describeTradingDays(days({ dayCount: 0 }))).toContain("Aucune séance");
  });

  it("omits the winning-session average when there was no winning session", () => {
    const text = describeTradingDays(days());
    expect(text).toContain("séance perdante moyenne");
    expect(text).not.toContain("séance gagnante moyenne");
  });

  it("never gives trading advice", () => {
    const texts = [
      describeDuration([bucket("< 2 min", 17, -781.68), bucket("> 1 h", 3, 200)]),
      describeGeneral(stats()),
      describeTradingDays(days()),
      describeSide([bucket("Achat", 5, 30), bucket("Vente", 25, -900)]),
    ];
    for (const text of texts) {
      for (const pattern of ADVICE_PATTERNS) {
        expect(text).not.toMatch(pattern);
      }
    }
  });
});
