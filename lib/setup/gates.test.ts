import { describe, expect, it } from "vitest";
import { evaluateViabilityGates } from "./gates";

// Same order of magnitude as S01's own EURUSD table: spread ~0.7 pip +
// commission ~0.2 pip round-trip.
const spread = 0.00007;
const commission = 0.00002;

describe("evaluateViabilityGates — cost gate", () => {
  it("refuses a tight stop whose cost exceeds the threshold (S01: EURUSD SL 3 pips -> c ~= 0.30)", () => {
    const result = evaluateViabilityGates({
      entryPrice: 1.1024,
      stopDistance: 0.0003, // 3 pips
      targetPrice: 1.1124, // plenty of R:R room, cost gate must be what blocks this
      side: "buy",
      spread,
      commission,
      costThreshold: 0.25,
      minRiskReward: 3,
    });
    expect(result.costRatio).toBeCloseTo(0.3, 2);
    expect(result.passed).toBe(false);
    expect(result.reason).toMatch(/porte de coût/);
  });

  it("passes a wider stop whose cost stays under the threshold (S01: EURUSD SL 7 pips -> c ~= 0.13)", () => {
    const result = evaluateViabilityGates({
      entryPrice: 1.1024,
      stopDistance: 0.0007, // 7 pips
      targetPrice: 1.1234, // 1:3 nominal, comfortably above 3 after cost
      side: "buy",
      spread,
      commission,
      costThreshold: 0.25,
      minRiskReward: 3,
    });
    expect(result.costRatio).toBeCloseTo(0.13, 2);
    expect(result.passed).toBe(true);
  });
});

describe("evaluateViabilityGates — R:R gate", () => {
  it("refuses when the real R:R (after cost) falls below the minimum, even with a cheap cost", () => {
    const result = evaluateViabilityGates({
      entryPrice: 1.1,
      stopDistance: 0.001,
      targetPrice: 1.102, // nominal 1:2 — below the 1:3 floor before cost even applies
      side: "buy",
      spread: 0.00002,
      commission: 0.00001,
      costThreshold: 0.25,
      minRiskReward: 3,
    });
    expect(result.passed).toBe(false);
    expect(result.reason).toMatch(/porte R:R/);
  });
});
