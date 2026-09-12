import { describe, expect, it } from "vitest";
import { evaluateSetup, proposeSetup, type SetupProposalInput } from "./proposal";
import { candleAt, series } from "@/lib/analysis/test-helpers";
import { DEFAULT_SESSION_WINDOWS } from "@/lib/analysis/config";

// Same bullish BOS shape used in bias.test.ts, reused on both H4 and D1 so
// dailyBias() resolves to "bullish".
const bullishHtf = series([
  { high: 10, low: 8, close: 9 },
  { high: 12, low: 9, close: 11 },
  { high: 11, low: 9, close: 10 },
  { high: 13, low: 10, close: 12.5 },
]);

// Same shape used in dealing-range.test.ts: external high 12, external low
// 8, equilibrium 10, last close 9.5 -> discount (required for a buy).
const h1Discount = series([
  { high: 10, low: 9, close: 9.5 },
  { high: 9, low: 8, close: 8.5 },
  { high: 10, low: 9, close: 9.5 },
  { high: 12, low: 10, close: 11 },
  { high: 10, low: 9, close: 9.5 },
]);

// Entry-timeframe candles start at minute 420 (07:00 UTC = London open, per
// DEFAULT_SESSION_WINDOWS) so none of them land in the Asia window — keeps
// liquidityPool's Asia-session detection out of this scenario entirely.
const at = (i: number, high: number, low: number, opts: { open?: number; close?: number } = {}) =>
  candleAt(420 + i, high, low, { ...opts, stepMinutes: 1, symbol: "EURUSD" });

// Two far equal highs (105.0, idx1 & idx4) -> the buy target. Two equal
// lows (99.0, idx6 & idx9) -> the sweep trigger candidate. A closer, more
// recent lone swing high (100.9, idx11) -> the level displacement must
// break (S01's "dernier swing opposé"), distinct from the far target.
const contextCandles = [
  at(0, 103.0, 102.5, { close: 102.8 }),
  at(1, 105.0, 102.6, { close: 102.9 }), // swing high #1 of the far target cluster
  at(2, 102.9, 102.4, { close: 102.6 }),
  at(3, 102.5, 101.0, { close: 101.5 }),
  at(4, 105.0, 101.2, { close: 101.5 }), // swing high #2 of the far target cluster
  at(5, 102.0, 100.0, { close: 100.2 }),
  at(6, 100.5, 99.0, { close: 99.3 }), // swing low #1 of the trigger cluster
  at(7, 100.3, 99.5, { close: 99.8 }),
  at(8, 100.2, 99.6, { close: 100.0 }), // kept flat so it doesn't form a spurious swing high
  at(9, 100.4, 99.0, { close: 99.4 }), // swing low #2 of the trigger cluster
  at(10, 100.7, 99.7, { close: 100.3 }),
  at(11, 100.9, 99.8, { close: 100.5 }), // recent lone swing high -> the level to break
  at(12, 100.6, 99.85, { close: 100.3 }),
];

// idx0: sweeps the 99.0 trigger level (low 98.7 < 99.0, close 99.2 > 99.0).
// idx1-3: calm. idx4: big bullish body closing well past 100.9, forming an
// unfilled FVG against idx2 -> the displacement.
const reactionCandles = [
  at(13, 99.4, 98.7, { close: 99.2 }),
  at(14, 99.5, 99.0, { open: 99.3, close: 99.3 }),
  at(15, 99.7, 99.2, { open: 99.5, close: 99.5 }),
  at(16, 99.9, 99.4, { open: 99.6, close: 99.6 }),
  at(17, 110.3, 100.0, { open: 100.0, close: 110.0 }),
];

function baseInput(): SetupProposalInput {
  return {
    symbol: "EURUSD",
    h4Candles: bullishHtf,
    d1Candles: bullishHtf,
    h1Candles: h1Discount,
    contextCandles,
    reactionCandles,
    swingLookback: 1,
    equalLevelTolerance: 0.3,
    sessionWindows: DEFAULT_SESSION_WINDOWS,
    atrPeriod: 14,
    minBodyAtrMultiple: 1.5,
    minFvgSize: 0.2,
    spreadBuffer: 0.05,
    spread: 0.1,
    commission: 0.02,
    costThreshold: 0.25,
    minRiskReward: 3,
  };
}

describe("proposeSetup — full sequence", () => {
  it("assembles a complete buy proposal when every step passes", () => {
    const proposal = proposeSetup(baseInput());
    expect(proposal).not.toBeNull();
    expect(proposal).toMatchObject({
      symbol: "EURUSD",
      side: "buy",
      sweptLevelKind: "equal_lows",
      sweptLevelPrice: 99,
      takeProfit: 105,
    });
    expect(proposal?.entryPrice).toBeCloseTo(99.85);
    expect(proposal?.stopLoss).toBeCloseTo(98.65);
    expect(proposal?.costRatio).toBeCloseTo(0.1, 2);
    expect(proposal?.riskRewardRatio).toBeGreaterThanOrEqual(3);
  });

  it("is null when H4 and D1 bias disagree", () => {
    const bearishHtf = series([
      { high: 12, low: 10, close: 11 },
      { high: 11, low: 8, close: 9 },
      { high: 11, low: 9, close: 10 },
      { high: 10, low: 7, close: 7.5 },
    ]);
    expect(proposeSetup({ ...baseInput(), d1Candles: bearishHtf })).toBeNull();
  });

  it("is null when price sits on the wrong side of the dealing range (premium, not discount, for a buy)", () => {
    // Same shape as h1Discount plus one bar, so idx3 stays a confirmed swing
    // high (a range still exists) while the final close lands above
    // equilibrium — genuinely a range_location rejection, not "no range".
    const h1Premium = series([
      { high: 10, low: 9, close: 9.5 },
      { high: 9, low: 8, close: 8.5 },
      { high: 10, low: 9, close: 9.5 },
      { high: 12, low: 10, close: 11 },
      { high: 10, low: 9, close: 9.5 },
      { high: 12, low: 11, close: 11.5 }, // above equilibrium -> premium
    ]);
    const outcome = evaluateSetup({ ...baseInput(), h1Candles: h1Premium });
    expect(outcome).toMatchObject({ status: "blocked", stage: "range_location" });
    expect(proposeSetup({ ...baseInput(), h1Candles: h1Premium })).toBeNull();
  });

  it("is null when the cost gate refuses (stop too tight for the spread/commission)", () => {
    expect(proposeSetup({ ...baseInput(), spread: 5, commission: 5 })).toBeNull();
  });
});

describe("evaluateSetup — blocked stage reporting", () => {
  it("reports 'proposed' with the full proposal on the success path", () => {
    const outcome = evaluateSetup(baseInput());
    expect(outcome.status).toBe("proposed");
  });

  it("reports stage 'bias' when H4/D1 disagree", () => {
    const bearishHtf = series([
      { high: 12, low: 10, close: 11 },
      { high: 11, low: 8, close: 9 },
      { high: 11, low: 9, close: 10 },
      { high: 10, low: 7, close: 7.5 },
    ]);
    const outcome = evaluateSetup({ ...baseInput(), d1Candles: bearishHtf });
    expect(outcome).toMatchObject({ status: "blocked", stage: "bias" });
  });

  it("reports stage 'liquidity' when no candidate levels exist", () => {
    const outcome = evaluateSetup({ ...baseInput(), contextCandles: contextCandles.slice(0, 2) });
    expect(outcome).toMatchObject({ status: "blocked", stage: "liquidity" });
  });

  it("reports stage 'sweep' when the level is never touched", () => {
    const noSweep = reactionCandles.map((c) => ({ ...c, low: 99.5, high: Math.max(c.high, 99.6) }));
    const outcome = evaluateSetup({ ...baseInput(), reactionCandles: noSweep });
    expect(outcome).toMatchObject({ status: "blocked", stage: "sweep" });
  });

  it("reports stage 'displacement' when the reclaim never breaks out", () => {
    const noDisplacement = [
      reactionCandles[0],
      ...reactionCandles.slice(1).map((c) => ({ ...c, close: 99.5, open: 99.4, high: 99.6 })),
    ];
    const outcome = evaluateSetup({ ...baseInput(), reactionCandles: noDisplacement });
    expect(outcome).toMatchObject({ status: "blocked", stage: "displacement" });
  });

  it("reports stage 'gates' when the cost gate refuses", () => {
    const outcome = evaluateSetup({ ...baseInput(), spread: 5, commission: 5 });
    expect(outcome).toMatchObject({ status: "blocked", stage: "gates" });
  });
});
