import { describe, expect, it } from "vitest";
import {
  bootstrapMeanCi,
  classifyVerdict,
  VERDICT_CRITERIA_2026_07_18,
  type VerdictTrade,
} from "./verdict";

const C = VERDICT_CRITERIA_2026_07_18;

/** Build a spread-out sample: `wins` at +2R net, `losses` at −1R net,
 *  alternating sides and months unless overridden. */
function sample(args: {
  wins: number;
  losses: number;
  side?: "buy" | "sell" | "alternate";
  months?: string[];
}): VerdictTrade[] {
  const months = args.months ?? ["2024-06", "2024-09", "2024-12", "2025-03"];
  const trades: VerdictTrade[] = [];
  const push = (netR: number, i: number) =>
    trades.push({
      netR,
      side: args.side === "buy" ? "buy" : args.side === "sell" ? "sell" : i % 2 === 0 ? "buy" : "sell",
      month: months[i % months.length],
    });
  for (let i = 0; i < args.wins; i += 1) push(2, i);
  for (let i = 0; i < args.losses; i += 1) push(-1, args.wins + i);
  return trades;
}

describe("pre-registered criteria are locked", () => {
  it("matches the user's 2026-07-18 bar verbatim", () => {
    expect(C).toEqual({
      minTrades: 100,
      minSideN: 30,
      passNetExpectancy: 0.05,
      sideFailExpectancy: -0.1,
      monthConcentrationMax: 0.5,
      bootstrapLowerBound: -0.05,
      bootstrapMaxWidth: 0.4,
      bootstrapIterations: 10_000,
      bootstrapSeed: 20_260_718,
    });
  });
});

describe("bootstrap", () => {
  it("is deterministic for a fixed seed", () => {
    const values = sample({ wins: 60, losses: 90 }).map((t) => t.netR);
    const a = bootstrapMeanCi(values, 2000, 42);
    const b = bootstrapMeanCi(values, 2000, 42);
    expect(a).toEqual(b);
  });

  it("brackets the sample mean", () => {
    const values = sample({ wins: 60, losses: 90 }).map((t) => t.netR);
    const mean = values.reduce((s, v) => s + v, 0) / values.length;
    const ci = bootstrapMeanCi(values, 5000, 7);
    expect(ci.lower).toBeLessThan(mean);
    expect(ci.upper).toBeGreaterThan(mean);
  });
});

describe("classifyVerdict", () => {
  it("PASS: strong balanced sample meets every criterion", () => {
    // 300 trades, 120 wins → exp = (240−180)/300 = +0.20R. n matches the
    // expected holdout scale (~300-400): at n=150 the bootstrap CI width
    // (~0.46R) exceeds the 0.40R cap by itself — the width rule is a variance
    // guard that effectively demands holdout-scale samples.
    const result = classifyVerdict(sample({ wins: 120, losses: 180 }), C);
    expect(result.outcome).toBe("PASS");
    expect(result.metrics.n).toBe(300);
    expect(result.metrics.netExpectancyR).toBeCloseTo(0.2, 4);
  });

  it("FAIL: non-positive net expectancy", () => {
    // 50 wins / 100 losses → exp = 0R exactly → ≤ 0.
    const result = classifyVerdict(sample({ wins: 50, losses: 100 }), C);
    expect(result.outcome).toBe("FAIL");
    expect(result.reasons.join(" ")).toContain("<= 0");
  });

  it("FAIL: a populated side bleeding <= -0.10R sinks an otherwise positive total", () => {
    // BUY: 40 wins +2 → strong. SELL: 10 wins, 80 losses → exp (20−80)/90 ≈ −0.67R.
    const trades = [
      ...sample({ wins: 40, losses: 20, side: "buy" }),
      ...sample({ wins: 10, losses: 80, side: "sell" }),
    ];
    const result = classifyVerdict(trades, C);
    expect(result.outcome).toBe("FAIL");
    expect(result.reasons.join(" ")).toContain("SELL");
  });

  it("FAIL: one month carrying more than half the net cumulative R", () => {
    // All wins in one month, tiny elsewhere → concentration > 50%.
    const trades: VerdictTrade[] = [
      ...Array.from({ length: 60 }, (_, i) => ({ netR: 2, side: (i % 2 ? "buy" : "sell") as "buy" | "sell", month: "2024-07" })),
      ...Array.from({ length: 90 }, (_, i) => ({ netR: i % 3 === 0 ? 0.5 : -1, side: (i % 2 ? "buy" : "sell") as "buy" | "sell", month: ["2024-08", "2024-09", "2024-10"][i % 3] })),
    ];
    const result = classifyVerdict(trades, C);
    expect(result.outcome).toBe("FAIL");
    expect(result.reasons.join(" ")).toContain("2024-07");
  });

  it("INCONCLUSIVE: n below 100 even when expectancy is strong", () => {
    const result = classifyVerdict(sample({ wins: 30, losses: 30 }), C);
    expect(result.outcome).toBe("INCONCLUSIVE");
    expect(result.reasons.join(" ")).toContain("n=60");
  });

  it("INCONCLUSIVE: positive but sub-bar expectancy (0 < exp < 0.05)", () => {
    // Months kept perfectly balanced (13 wins + 25 losses each → +1R per
    // month, 25% share) so the concentration FAIL cannot fire; exp =
    // (104−100)/152 ≈ +0.026R sits in the 0..0.05 inconclusive band.
    const months = ["2024-06", "2024-09", "2024-12", "2025-03"];
    const trades: VerdictTrade[] = [];
    for (let m = 0; m < 4; m += 1) {
      for (let i = 0; i < 13; i += 1)
        trades.push({ netR: 2, side: i % 2 ? "buy" : "sell", month: months[m] });
      for (let i = 0; i < 25; i += 1)
        trades.push({ netR: -1, side: i % 2 ? "buy" : "sell", month: months[m] });
    }
    const result = classifyVerdict(trades, C);
    expect(result.outcome).toBe("INCONCLUSIVE");
    expect(result.reasons.join(" ")).toContain("0.05");
  });

  it("FAIL precedence: a FAIL condition beats an INCONCLUSIVE band", () => {
    // exp +0.02R would be INCONCLUSIVE, but one month carries 67% of a barely
    // positive total → month-dependence FAIL wins. A fragile positive is a
    // fail, not a maybe.
    const result = classifyVerdict(sample({ wins: 51, losses: 99 }), C);
    expect(result.outcome).toBe("FAIL");
    expect(result.reasons.join(" ")).toContain("net cumulative R");
  });

  it("INCONCLUSIVE: an underpopulated side blocks PASS without failing", () => {
    // SELL n=10 (< 30) but not populated enough to FAIL on side expectancy.
    const trades = [
      ...sample({ wins: 60, losses: 80, side: "buy" }),
      ...sample({ wins: 4, losses: 6, side: "sell" }),
    ];
    const result = classifyVerdict(trades, C);
    expect(result.outcome).toBe("INCONCLUSIVE");
    expect(result.reasons.join(" ")).toContain("SELL n=10");
  });
});
