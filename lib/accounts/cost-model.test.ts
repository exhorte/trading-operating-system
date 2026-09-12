import { describe, expect, it } from "vitest";
import { commissionInPriceUnits, expectedSpread } from "./cost-model";
import type { CostModel } from "./types";
import { symbolMetadata } from "@/lib/market/symbols/registry";

const eurusd = symbolMetadata("EURUSD")!;

describe("commissionInPriceUnits", () => {
  it("converts a $5/lot round-trip commission into EURUSD price units", () => {
    const model: CostModel = {
      commissionPerLotRoundTrip: 5,
      expectedSpreadBySymbol: {},
      costThreshold: 0.25,
    };
    // tickSize/tickValue = 0.00001/1.0 = 0.00001 price units per $1.
    expect(commissionInPriceUnits(model, eurusd)).toBeCloseTo(0.00005, 8);
  });

  it("is zero commission for a raw account with no per-lot fee", () => {
    const model: CostModel = {
      commissionPerLotRoundTrip: 0,
      expectedSpreadBySymbol: {},
      costThreshold: 0.25,
    };
    expect(commissionInPriceUnits(model, eurusd)).toBe(0);
  });

  it("guards against a degenerate tickValue of 0 rather than dividing by it", () => {
    const model: CostModel = {
      commissionPerLotRoundTrip: 5,
      expectedSpreadBySymbol: {},
      costThreshold: 0.25,
    };
    expect(commissionInPriceUnits(model, { ...eurusd, tickValue: 0 })).toBe(0);
  });
});

describe("expectedSpread", () => {
  it("returns the documented spread for a known symbol", () => {
    const model: CostModel = {
      commissionPerLotRoundTrip: 5,
      expectedSpreadBySymbol: { EURUSD: 0.00015 },
      costThreshold: 0.25,
    };
    expect(expectedSpread(model, "EURUSD")).toBe(0.00015);
  });

  it("returns null when the model has no entry for the symbol", () => {
    const model: CostModel = {
      commissionPerLotRoundTrip: 5,
      expectedSpreadBySymbol: {},
      costThreshold: 0.25,
    };
    expect(expectedSpread(model, "GBPUSD")).toBeNull();
  });
});
