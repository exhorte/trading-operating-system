import { describe, expect, it } from "vitest";
import { clipHoldout, isHoldoutTime, onlyHoldout, VIRGIN_HOLDOUT } from "./holdout";
import type { Candle } from "@/lib/domain/market";

function candle(openTime: string): Candle {
  return {
    symbol: "XAUUSDm", timeframe: "M15", openTime,
    open: 1, high: 2, low: 0, close: 1, volume: 1, closed: true,
  };
}

describe("virgin holdout boundaries (user-fixed 2026-07-18)", () => {
  it("start is inclusive, end is exclusive — the dev set's first candle is OUT", () => {
    expect(isHoldoutTime("2024-06-01T00:00:00.000Z")).toBe(true); // first holdout instant
    expect(isHoldoutTime("2025-06-06T13:15:00.000Z")).toBe(true); // last holdout candle
    expect(isHoldoutTime("2025-06-06T13:30:00.000Z")).toBe(false); // dev candle #1 — excluded
    expect(isHoldoutTime("2024-05-31T23:45:00.000Z")).toBe(false); // before the window
  });

  it("declares the agreed window verbatim", () => {
    expect(VIRGIN_HOLDOUT.fromUtc).toBe("2024-06-01T00:00:00.000Z");
    expect(VIRGIN_HOLDOUT.toUtc).toBe("2025-06-06T13:30:00.000Z");
  });
});

describe("clip / only", () => {
  const series = [
    candle("2024-05-31T23:45:00.000Z"), // before
    candle("2024-08-15T10:00:00.000Z"), // inside
    candle("2025-06-06T13:15:00.000Z"), // inside (last)
    candle("2025-06-06T13:30:00.000Z"), // dev set start
  ];

  it("clipHoldout removes exactly the holdout candles and counts them", () => {
    const { kept, removed } = clipHoldout(series);
    expect(removed).toBe(2);
    expect(kept.map((c) => c.openTime)).toEqual([
      "2024-05-31T23:45:00.000Z",
      "2025-06-06T13:30:00.000Z",
    ]);
  });

  it("onlyHoldout keeps exactly the holdout candles (verdict mode)", () => {
    expect(onlyHoldout(series).map((c) => c.openTime)).toEqual([
      "2024-08-15T10:00:00.000Z",
      "2025-06-06T13:15:00.000Z",
    ]);
  });
});
