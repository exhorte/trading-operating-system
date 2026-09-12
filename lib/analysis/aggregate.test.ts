import { describe, expect, it } from "vitest";
import { aggregateCandles } from "./aggregate";
import { candleAt } from "./test-helpers";

// candleAt defaults to stepMinutes=15; every call here is explicit about
// stepMinutes=1 so index == minute-of-hour, matching real M1 spacing.
const m1 = (index: number, high: number, low: number, opts: Record<string, unknown> = {}) =>
  candleAt(index, high, low, { ...opts, stepMinutes: 1 });

describe("aggregateCandles", () => {
  it("merges M1 candles into one H1 bucket: open=first, close=last, high=max, low=min, volume=sum", () => {
    // BASE_EPOCH is 2026-01-05T00:00:00Z -> indices 0-2 all fall in [00:00,01:00).
    const source = [
      m1(0, 1.101, 1.099, { open: 1.1, close: 1.1005 }),
      m1(1, 1.103, 1.1, { open: 1.1005, close: 1.102 }),
      m1(2, 1.102, 1.098, { open: 1.102, close: 1.099 }),
    ];
    const h1 = aggregateCandles(source, "M1", "H1");
    expect(h1).toHaveLength(1);
    expect(h1[0]).toMatchObject({
      timeframe: "H1",
      openTime: "2026-01-05T00:00:00.000Z",
      open: 1.1,
      close: 1.099,
      high: 1.103,
      low: 1.098,
      volume: 300, // test-helpers default volume 100 per candle, x3
      closed: false, // only 3 of the 60 expected M1 members are present
    });
  });

  it("starts a new bucket once the candle's open time crosses the boundary", () => {
    const source = [
      m1(59, 1.101, 1.099), // 00:59, last minute of the first H1 bucket
      m1(60, 1.105, 1.104), // 01:00, first minute of the next bucket
    ];
    const h1 = aggregateCandles(source, "M1", "H1");
    expect(h1).toHaveLength(2);
    expect(h1[0].openTime).toBe("2026-01-05T00:00:00.000Z");
    expect(h1[1].openTime).toBe("2026-01-05T01:00:00.000Z");
  });

  it("marks a bucket closed only once it holds every expected member and the last one is itself closed", () => {
    const full60 = Array.from({ length: 60 }, (_, i) => m1(i, 1.1 + i * 0.0001, 1.1));
    const h1Full = aggregateCandles(full60, "M1", "H1");
    expect(h1Full[0].closed).toBe(true);

    const forming = full60.slice(0, 59).concat({ ...full60[59], closed: false });
    const h1Forming = aggregateCandles(forming, "M1", "H1");
    expect(h1Forming[0].closed).toBe(false);
  });

  it("returns an empty array for an empty input", () => {
    expect(aggregateCandles([], "M1", "H1")).toEqual([]);
  });
});
