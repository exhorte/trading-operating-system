import { describe, expect, it } from "vitest";
import { computeMetrics } from "./metrics";
import type { SimulatedTrade } from "./outcome";

const win = (r = 2): SimulatedTrade => ({ outcome: "win", rMultiple: r, barsHeld: 3, exitPrice: 0, bothTouch: false });
const loss = (): SimulatedTrade => ({ outcome: "loss", rMultiple: -1, barsHeld: 2, exitPrice: 0, bothTouch: false });
const timeout = (r: number): SimulatedTrade => ({ outcome: "timeout", rMultiple: r, barsHeld: 10, exitPrice: 0, bothTouch: false });

describe("computeMetrics", () => {
  it("computes win rate over decided trades, expectancy over all", () => {
    const m = computeMetrics([win(), win(), loss(), loss(), timeout(0.5)]);
    expect(m.tradeCount).toBe(5);
    expect(m.winRate).toBe(50); // 2/4 decided
    expect(m.avgR).toBe(0.5); // (2+2-1-1)/4
    expect(m.expectancyR).toBe(0.5); // (2+2-1-1+0.5)/5 = 0.5
    expect(m.cumulativeR).toBe(2.5);
    expect(m.timeoutCount).toBe(1);
  });

  it("tracks max consecutive losses (negative timeouts count as losses)", () => {
    const m = computeMetrics([loss(), loss(), timeout(-0.3), win(), loss()]);
    expect(m.maxConsecutiveLosses).toBe(3);
  });

  it("is safe on an empty run", () => {
    const m = computeMetrics([]);
    expect(m.winRate).toBe(0);
    expect(m.expectancyR).toBe(0);
    expect(m.cumulativeR).toBe(0);
  });
});
