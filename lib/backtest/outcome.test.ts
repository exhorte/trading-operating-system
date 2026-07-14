import { describe, expect, it } from "vitest";
import { simulateTradeOutcome } from "./outcome";
import { series } from "@/lib/analysis/test-helpers";

// buy @100, SL 95 (risk 5), TP 110 (2R)
const base = { side: "buy" as const, entryPrice: 100, stopLoss: 95, takeProfit: 110, maxBars: 10 };

describe("simulateTradeOutcome", () => {
  it("wins at 2R when the target is touched first", () => {
    const trade = simulateTradeOutcome({
      ...base,
      futureCandles: series([
        [104, 98], // neither
        [111, 103], // touches 110
      ]),
    });
    expect(trade).toMatchObject({ outcome: "win", rMultiple: 2, barsHeld: 2, exitPrice: 110, bothTouch: false });
  });

  it("loses -1R when the stop is touched first", () => {
    const trade = simulateTradeOutcome({
      ...base,
      futureCandles: series([
        [103, 94], // low 94 <= 95
      ]),
    });
    expect(trade).toMatchObject({ outcome: "loss", rMultiple: -1, barsHeld: 1, bothTouch: false });
  });

  it("applies the conservative rule on a both-touch bar: loss, flagged", () => {
    const trade = simulateTradeOutcome({
      ...base,
      futureCandles: series([
        [112, 94], // touches BOTH 110 and 95
      ]),
    });
    expect(trade).toMatchObject({ outcome: "loss", rMultiple: -1, bothTouch: true });
  });

  it("times out at maxBars and exits at the close", () => {
    const trade = simulateTradeOutcome({
      ...base,
      maxBars: 2,
      futureCandles: series([
        { high: 104, low: 98, close: 102 },
        { high: 105, low: 99, close: 102.5 }, // exit here: +2.5 on risk 5 = 0.5R
        { high: 120, low: 99, close: 119 }, // beyond horizon — must be ignored
      ]),
    });
    expect(trade).toMatchObject({ outcome: "timeout", rMultiple: 0.5, barsHeld: 2, exitPrice: 102.5 });
  });

  it("handles sell side symmetrically", () => {
    const trade = simulateTradeOutcome({
      side: "sell",
      entryPrice: 100,
      stopLoss: 105,
      takeProfit: 90,
      maxBars: 10,
      futureCandles: series([
        [102, 89], // low 89 <= 90 target, high 102 < 105 stop
      ]),
    });
    expect(trade).toMatchObject({ outcome: "win", rMultiple: 2 });
  });

  it("returns null on zero risk or no future bars", () => {
    expect(simulateTradeOutcome({ ...base, stopLoss: 100, futureCandles: series([[101, 99]]) })).toBeNull();
    expect(simulateTradeOutcome({ ...base, futureCandles: [] })).toBeNull();
  });
});
