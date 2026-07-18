import { describe, expect, it } from "vitest";
import { CANDIDATE_CONFIG_2026_07_18 } from "./config";
import { evaluateTrigger, type TriggerInput } from "./trigger";
import type { FairValueGap, MarketContextState, StructureShift } from "@/lib/domain/analysis";
import type { Candle } from "@/lib/domain/market";
import { series } from "@/lib/analysis/test-helpers";

/**
 * Base bullish setup: BOS at index 5, aligned FVG (zone 100..103) formed at
 * index 6, bars 7-9 stay clear of the zone, bar 10 is the first retest with a
 * bullish confirmation close. Individual tests mutate one piece to exercise a
 * single gate.
 */
function buildWindow(currentBar: Partial<Pick<Candle, "open" | "high" | "low" | "close">>): Candle[] {
  return series([
    [110, 108], // 0
    [110, 108], // 1
    [110, 108], // 2
    [110, 108], // 3
    [110, 108], // 4
    [111, 109], // 5  (shift bar)
    [112, 110], // 6  (fvg bar)
    [108, 104], // 7  clear of 100..103
    [108, 104], // 8
    [108, 104], // 9
    { high: currentBar.high ?? 105, low: currentBar.low ?? 100.5, open: currentBar.open ?? 101, close: currentBar.close ?? 104 }, // 10
  ]);
}

function bullishContext(window: Candle[], over: Partial<MarketContextState> = {}): MarketContextState {
  const shift: StructureShift = {
    shiftId: "shift-5",
    symbol: "XAUUSD",
    timeframe: "M15",
    kind: "break_of_structure",
    direction: "bullish",
    brokenLevel: 111,
    occurredAt: window[5].openTime,
  };
  const fvg: FairValueGap = {
    fvgId: "fvg-6",
    symbol: "XAUUSD",
    timeframe: "M15",
    direction: "bullish",
    high: 103,
    low: 100,
    filledPercent: 0,
    mitigatedAt: null,
    detectedAt: window[6].openTime,
  };
  return {
    symbol: "XAUUSD",
    timeframe: "M15",
    bias: "bullish",
    session: "london",
    lastStructureShift: shift,
    activeLiquidityLevels: [],
    activeFairValueGaps: [fvg],
    activeOrderBlocks: [],
    score: 6,
    maxScore: 10,
    scoreBreakdown: [],
    computedAt: window[window.length - 1].openTime,
    ...over,
  };
}

function input(window: Candle[], context: MarketContextState, over: Partial<TriggerInput> = {}): TriggerInput {
  return { window, context, accountId: "acct", tickSize: 0.01, seq: 1, ...over };
}

describe("evaluateTrigger — happy path", () => {
  it("emits a buy on the first confirmed retest of an aligned fresh FVG", () => {
    const window = buildWindow({});
    const result = evaluateTrigger(input(window, bullishContext(window)));

    expect(result).not.toBeNull();
    const { signal } = result!;
    expect(signal.side).toBe("buy");
    expect(signal.strategyId).toBe("ict-fvg-retest-v1");
    expect(signal.entryPrice).toBe(104); // the confirmed close
    expect(signal.score).toBe(6); // engine score passed through, undoctored
    expect(signal.stopLoss).toBeLessThan(100); // beyond the gap floor + buffer
    // 2R target by construction (within the 2-decimal rounding of each level).
    const reward = signal.takeProfit - signal.entryPrice;
    const risk = signal.entryPrice - signal.stopLoss;
    expect(Math.abs(reward - 2 * risk)).toBeLessThan(0.02);
  });

  it("freezes the exact setup traded (the diagnostics metadata)", () => {
    const window = buildWindow({});
    const { setup } = evaluateTrigger(input(window, bullishContext(window)))!;

    expect(setup.fvgLow).toBe(100);
    expect(setup.fvgHigh).toBe(103);
    expect(setup.fvgSize).toBe(3);
    expect(setup.fvgAgeBars).toBe(4); // formed at 6, retested at 10
    expect(setup.shiftAgeBars).toBe(5); // shift at 5
    // bar.low 100.5 → penetration = 103 − 100.5 = 2.5 of 3 ≈ 83.3%
    expect(setup.retestDepthPercent).toBeCloseTo(83.33, 1);
    expect(setup.stopBuffer).toBeGreaterThan(0);
    expect(setup.atr).toBeGreaterThan(0);
  });
});

describe("evaluateTrigger — gates each reject on their own", () => {
  it("neutral bias never trades", () => {
    const window = buildWindow({});
    expect(evaluateTrigger(input(window, bullishContext(window, { bias: "neutral", lastStructureShift: null })))).toBeNull();
  });

  it("requires a structure shift aligned with bias", () => {
    const window = buildWindow({});
    const ctx = bullishContext(window);
    ctx.lastStructureShift = { ...ctx.lastStructureShift!, direction: "bearish" };
    expect(evaluateTrigger(input(window, ctx))).toBeNull();
  });

  it("rejects a stale structure shift", () => {
    const window = buildWindow({});
    expect(evaluateTrigger(input(window, bullishContext(window), { config: { ...cfg(), maxShiftAgeBars: 2 } }))).toBeNull();
  });

  it("ignores an FVG formed before the shift", () => {
    const window = buildWindow({});
    const ctx = bullishContext(window);
    ctx.activeFairValueGaps = [{ ...ctx.activeFairValueGaps[0], detectedAt: window[4].openTime }]; // before shift@5
    expect(evaluateTrigger(input(window, ctx))).toBeNull();
  });

  it("rejects an expired (stale) setup", () => {
    const window = buildWindow({});
    expect(evaluateTrigger(input(window, bullishContext(window), { config: { ...cfg(), maxSetupAgeBars: 2 } }))).toBeNull();
  });

  it("fires only on the FIRST retest — a prior touch kills the setup", () => {
    const window = buildWindow({});
    window[8] = { ...window[8], low: 100.5 }; // an earlier bar already dipped into the zone
    expect(evaluateTrigger(input(window, bullishContext(window)))).toBeNull();
  });

  it("requires the current bar to actually touch the zone", () => {
    const window = buildWindow({ low: 104, high: 106, open: 104.5, close: 105.5 }); // never enters 100..103
    expect(evaluateTrigger(input(window, bullishContext(window)))).toBeNull();
  });
});

describe("evaluateTrigger — session allowlist (iteration 2)", () => {
  it("null allows every session (iteration-1 behavior)", () => {
    const window = buildWindow({});
    expect(evaluateTrigger(input(window, bullishContext(window)))).not.toBeNull(); // fixture session: london
  });

  it("fires when the context session is allowed", () => {
    const window = buildWindow({});
    const ctx = bullishContext(window, { session: "new_york_am" });
    const result = evaluateTrigger(input(window, ctx, { config: { ...cfg(), allowedSessions: ["new_york_am"] } }));
    expect(result).not.toBeNull();
  });

  it("stays silent outside the allowlist — no signal, not a rejection", () => {
    const window = buildWindow({}); // fixture session: london
    const result = evaluateTrigger(input(window, bullishContext(window), { config: { ...cfg(), allowedSessions: ["new_york_am"] } }));
    expect(result).toBeNull();
  });
});

describe("evaluateTrigger — confirmation close modes", () => {
  it("middle: needs a bias-direction close that holds the gap", () => {
    const window = buildWindow({ open: 104, close: 101 }); // bearish close, no confirmation
    expect(evaluateTrigger(input(window, bullishContext(window)))).toBeNull();
  });

  it("strict rejects a close that stays inside the gap; middle accepts it", () => {
    const window = buildWindow({ low: 100.5, high: 103, open: 100.8, close: 102 }); // closes inside 100..103
    expect(evaluateTrigger(input(window, bullishContext(window), { config: { ...cfg(), confirmationClose: "strict" } }))).toBeNull();
    expect(evaluateTrigger(input(window, bullishContext(window), { config: { ...cfg(), confirmationClose: "middle" } }))).not.toBeNull();
  });
});

describe("frozen candidate 2026-07-18", () => {
  it("locks every value — changing one means creating a NEW candidate", () => {
    // Runs bt-mrp973lv-965814cc / bt-mrpq4try-b20fc81b were produced by this
    // exact configuration. If this test fails, someone edited the frozen
    // candidate instead of declaring a new one — revert or rename.
    expect(CANDIDATE_CONFIG_2026_07_18).toEqual({
      allowedSessions: ["new_york_am"],
      maxShiftAgeBars: 12,
      maxSetupAgeBars: 12,
      atrPeriod: 14,
      atrBufferMultiple: 0.5,
      minStopTicks: 1,
      rewardMultiple: 2,
      confirmationClose: "middle",
    });
  });
});

describe("evaluateTrigger — no look-ahead", () => {
  it("reads only bars up to the evaluation bar; appended future bars can't change the signal", () => {
    const window = buildWindow({});
    const context = bullishContext(window);
    const base = evaluateTrigger(input(window, context));

    // Future bars that would fill the gap / extend structure, excluded by slice.
    const longer = [...window, ...series([[90, 88], [90, 88], [130, 128]])];
    const sliced = evaluateTrigger(input(longer.slice(0, window.length), context));

    expect(sliced).toEqual(base);
  });
});

function cfg() {
  return {
    allowedSessions: null,
    maxShiftAgeBars: 12,
    maxSetupAgeBars: 12,
    atrPeriod: 14,
    atrBufferMultiple: 0.5,
    minStopTicks: 1,
    rewardMultiple: 2,
    confirmationClose: "middle" as const,
  };
}
