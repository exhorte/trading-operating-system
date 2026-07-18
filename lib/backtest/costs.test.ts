import { describe, expect, it } from "vitest";
import {
  FROZEN_COST_PROFILE_2026_07_18,
  STRESS_COST_PROFILE,
  roundTripCostR,
  rolloverCrossings,
  swapCostR,
  type SwapSpec,
} from "./costs";

describe("frozen cost profile (user-fixed 2026-07-18)", () => {
  it("locks the calibrated values — editing means re-freezing with the user", () => {
    expect(FROZEN_COST_PROFILE_2026_07_18).toMatchObject({
      spreadPoints: 0.26, // max(floor 0.20, observed p95 0.26)
      slippagePointsPerLeg: 0.05,
      commissionUsdPerLotPerSide: 0,
      contractSize: 100,
      swap: null,
    });
    expect(STRESS_COST_PROFILE).toMatchObject({
      spreadPoints: 0.3, // max(0.30, p99 0.26)
      slippagePointsPerLeg: 0.1,
      commissionUsdPerLotPerSide: 0,
    });
  });
});

describe("roundTripCostR", () => {
  it("charges spread + both slippage legs + commission, per unit of risk", () => {
    // 0.26 + 2×0.05 + 0 = 0.36 points; risk 12 points → 0.03R.
    expect(roundTripCostR(FROZEN_COST_PROFILE_2026_07_18, 12)).toBeCloseTo(0.03, 6);
  });

  it("is volume-independent and converts commission through contractSize", () => {
    const withCommission = { ...FROZEN_COST_PROFILE_2026_07_18, commissionUsdPerLotPerSide: 3.5 };
    // commission points = 2×3.5/100 = 0.07 → total 0.43 points; risk 10 → 0.043R.
    expect(roundTripCostR(withCommission, 10)).toBeCloseTo(0.043, 6);
  });

  it("returns 0 on degenerate risk", () => {
    expect(roundTripCostR(FROZEN_COST_PROFILE_2026_07_18, 0)).toBe(0);
  });
});

const swap: SwapSpec = {
  rolloverHourUtc: 21,
  longUsdPerLotPerNight: -25,
  shortUsdPerLotPerNight: 10,
  tripleSwapWeekdayUtc: 3, // Wednesday
};

describe("rolloverCrossings", () => {
  it("counts no crossing when the trade dies before the rollover", () => {
    // Tue 2026-07-14 signal 14:00 UTC, entry 14:15, 8 bars → exit 16:15.
    expect(
      rolloverCrossings({ signalOpenTimeIso: "2026-07-14T14:00:00.000Z", barsHeld: 8, barMinutes: 15, swap }),
    ).toBe(0);
  });

  it("counts one crossing when the holding period passes 21:00 UTC", () => {
    // Tue signal 15:45, entry 16:00, 25 bars → exit 22:15 → crosses Tue 21:00.
    expect(
      rolloverCrossings({ signalOpenTimeIso: "2026-07-14T15:45:00.000Z", barsHeld: 25, barMinutes: 15, swap }),
    ).toBe(1);
  });

  it("counts the triple-swap weekday as 3", () => {
    // Wed 2026-07-15 signal 15:45, entry 16:00, 25 bars → crosses Wed 21:00 → 3.
    expect(
      rolloverCrossings({ signalOpenTimeIso: "2026-07-15T15:45:00.000Z", barsHeld: 25, barMinutes: 15, swap }),
    ).toBe(3);
  });
});

describe("swapCostR", () => {
  const profile = { ...FROZEN_COST_PROFILE_2026_07_18, swap };

  it("charges a negative long rate as a positive cost", () => {
    // -25 USD/lot → -0.25 points per night; risk 10 → costR +0.025.
    expect(swapCostR({ profile, side: "buy", crossings: 1, riskDistance: 10 })).toBeCloseTo(0.025, 6);
  });

  it("credits a positive short rate as a negative cost", () => {
    expect(swapCostR({ profile, side: "sell", crossings: 1, riskDistance: 10 })).toBeCloseTo(-0.01, 6);
  });

  it("is zero when swap is unmodeled or there are no crossings — the runner must refuse instead", () => {
    expect(swapCostR({ profile: FROZEN_COST_PROFILE_2026_07_18, side: "buy", crossings: 2, riskDistance: 10 })).toBe(0);
    expect(swapCostR({ profile, side: "buy", crossings: 0, riskDistance: 10 })).toBe(0);
  });
});
