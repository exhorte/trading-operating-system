/**
 * Conservative cost model (Phase 13). Pure — a POST-PROCESSING layer.
 *
 * The outcome simulation (binary SL/TP, conservative both-touch, timeout at
 * horizon close) is untouched, so gross R stays comparable across every run.
 * Each trade gets costR (adverse round trip) and netR = grossR − costR.
 *
 * Honest limits: constant spread (no historical series), constant slippage,
 * and the model ignores spread's effect on the trigger levels themselves
 * (bid-quoted SL touch vs ask-quoted entry). The conservative constants are
 * the compensation; net numbers bound realism from below, they are not an
 * account simulation.
 */

import type { Side } from "@/lib/domain/primitives";

/** Broker swap specification. `null` on a profile means swap is NOT modeled —
 *  and the verdict must then be REFUSED if any trade crosses a rollover
 *  (user invariant 2026-07-18: never assume a zero swap). */
export interface SwapSpec {
  /** UTC hour at which the broker charges swap (server midnight). */
  rolloverHourUtc: number;
  /** USD per lot per night; negative = cost. */
  longUsdPerLotPerNight: number;
  shortUsdPerLotPerNight: number;
  /** UTC weekday (0=Sun…6=Sat) whose crossing counts 3× (weekend charge). */
  tripleSwapWeekdayUtc: number;
}

export interface CostProfile {
  name: string;
  spreadPoints: number;
  slippagePointsPerLeg: number;
  commissionUsdPerLotPerSide: number;
  /** Units per 1.0 lot (XAUUSD: 100 oz) — converts USD/lot to price points. */
  contractSize: number;
  swap: SwapSpec | null;
  /** Where every number comes from — auditability over convenience. */
  provenance: string;
}

/**
 * FROZEN COST PROFILE — fixed 2026-07-18 per the user's Phase 13 validation,
 * BEFORE the anterior import and the verdict run.
 *
 * spreadApplied = max(spreadFloor 0.20, observed p95) = 0.26. Calibration
 * caveat, surfaced for review: the stored ticks contain ZERO NY AM
 * observations — the only observed window is London 2026-07-12 09:26→10:20
 * UTC (n=3,158, spread constant 0.26 = p50 = p95 = p99). Using the 0.20 floor
 * when 0.26 was observed would be anti-conservative, so 0.26 is persisted.
 * Recalibrate ONLY by collecting real NY AM ticks BEFORE the verdict run.
 *
 * swap: null — Exness XAUUSDm swap rates were not provided. The verdict
 * refuses itself if any trade crosses the rollover while this is null.
 */
export const FROZEN_COST_PROFILE_2026_07_18: CostProfile = {
  name: "xauusdm-standard-frozen-2026-07-18",
  spreadPoints: 0.26,
  slippagePointsPerLeg: 0.05,
  commissionUsdPerLotPerSide: 0,
  contractSize: 100,
  swap: null,
  provenance:
    "spread = max(floor 0.20, p95 observed 0.26); observation = 3,158 stored live ticks, " +
    "single London window 2026-07-12 09:26-10:20 UTC, constant 0.26 (no NY AM ticks stored); " +
    "slippage 0.05/leg and commission 0 (Standard account) fixed by the user 2026-07-18; " +
    "swap not modeled - verdict refuses on rollover crossings.",
};

/** Informative stress scenario (user 2026-07-18). NEVER modifies the
 *  candidate or the verdict — reported alongside it. */
export const STRESS_COST_PROFILE: CostProfile = {
  name: "xauusdm-stress-informative",
  spreadPoints: 0.3, // max(0.30, p99 observed 0.26)
  slippagePointsPerLeg: 0.1,
  commissionUsdPerLotPerSide: 0,
  contractSize: 100,
  swap: null,
  provenance: "stress: spread max(0.30, p99 0.26)=0.30, slippage 0.10/leg, commission 0.",
};

/** Adverse round-trip cost in R for a trade with the given risk distance.
 *  Volume cancels out (cost and risk both scale with it). */
export function roundTripCostR(profile: CostProfile, riskDistance: number): number {
  if (riskDistance <= 0) {
    return 0;
  }
  const commissionPoints = (2 * profile.commissionUsdPerLotPerSide) / profile.contractSize;
  const costPoints = profile.spreadPoints + 2 * profile.slippagePointsPerLeg + commissionPoints;
  return costPoints / riskDistance;
}

/**
 * Count broker rollovers strictly inside a trade's holding period.
 * Entry moment = signal bar close (openTime + barMinutes); exit moment =
 * openTime + (1 + barsHeld) × barMinutes (outcome.ts bar convention).
 * A crossing on the triple-swap weekday counts 3 (weekend charge).
 */
export function rolloverCrossings(args: {
  signalOpenTimeIso: string;
  barsHeld: number;
  barMinutes: number;
  swap: SwapSpec;
}): number {
  const { signalOpenTimeIso, barsHeld, barMinutes, swap } = args;
  const entryMs = Date.parse(signalOpenTimeIso) + barMinutes * 60_000;
  const exitMs = Date.parse(signalOpenTimeIso) + (1 + barsHeld) * barMinutes * 60_000;

  // First rollover instant at or after entry (exclusive of entry itself).
  const first = new Date(entryMs);
  first.setUTCHours(swap.rolloverHourUtc, 0, 0, 0);
  let t = first.getTime();
  while (t <= entryMs) {
    t += 24 * 60 * 60_000;
  }

  let crossings = 0;
  while (t <= exitMs) {
    crossings += new Date(t).getUTCDay() === swap.tripleSwapWeekdayUtc ? 3 : 1;
    t += 24 * 60 * 60_000;
  }
  return crossings;
}

/** Swap cost in R (positive = cost) for the given crossings. Swap rates are
 *  signed (negative = charge); the R cost is the NEGATIVE of the credit. */
export function swapCostR(args: {
  profile: CostProfile;
  side: Side;
  crossings: number;
  riskDistance: number;
}): number {
  const { profile, side, crossings, riskDistance } = args;
  if (profile.swap === null || crossings === 0 || riskDistance <= 0) {
    return 0;
  }
  const usdPerLot =
    side === "buy" ? profile.swap.longUsdPerLotPerNight : profile.swap.shortUsdPerLotPerNight;
  const points = (usdPerLot / profile.contractSize) * crossings;
  return -points / riskDistance; // negative rate (cost) → positive costR
}
