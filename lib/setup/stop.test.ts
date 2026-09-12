import { describe, expect, it } from "vitest";
import { computeStopLoss } from "./stop";

describe("computeStopLoss", () => {
  it("places a buy stop below the sweep's wick extreme, minus the spread buffer", () => {
    const result = computeStopLoss("buy", 1.098, 0.0002, 1.1024);
    expect(result?.price).toBeCloseTo(1.0978);
    expect(result?.distance).toBeCloseTo(1.1024 - 1.0978);
  });

  it("places a sell stop above the sweep's wick extreme, plus the spread buffer", () => {
    const result = computeStopLoss("sell", 1.102, 0.0002, 1.0976);
    expect(result?.price).toBeCloseTo(1.1022);
  });

  it("refuses a stop wider than the calibrated ceiling", () => {
    expect(computeStopLoss("buy", 1.09, 0.0002, 1.1024, 0.005)).toBeNull();
  });

  it("applies no ceiling when maxDistance is not provided", () => {
    expect(computeStopLoss("buy", 1.09, 0.0002, 1.1024)).not.toBeNull();
  });
});
