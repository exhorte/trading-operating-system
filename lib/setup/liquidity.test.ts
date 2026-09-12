import { describe, expect, it } from "vitest";
import { liquidityPool, opposingTarget, sweepTriggerCandidate } from "./liquidity";
import { DEFAULT_SESSION_WINDOWS } from "@/lib/analysis/config";
import { series } from "@/lib/analysis/test-helpers";
import type { LiquidityLevel } from "@/lib/domain/analysis";

describe("liquidityPool — Asia session high/low", () => {
  // stepMinutes=60 from 2026-01-05T00:00 UTC: idx0-6 fall in the Asia window
  // (23:00-07:00), idx7-9 in London (07:00-12:00) — see DEFAULT_SESSION_WINDOWS.
  const candles = series(
    [
      [1.105, 1.101], // 0
      [1.106, 1.1005], // 1
      [1.1055, 1.102], // 2
      [1.107, 1.099], // 3  asia low 1.099
      [1.108, 1.1], // 4    asia high 1.108
      [1.104, 1.101], // 5
      [1.103, 1.1015], // 6
      [1.1035, 1.102], // 7  london, doesn't touch either level
      [1.104, 1.1015], // 8  london
      [1.1045, 1.1018], // 9 london
    ],
    { stepMinutes: 60 },
  );

  it("picks the high/low of only the most recent contiguous Asia block", () => {
    const pool = liquidityPool(candles, [], 0.3, DEFAULT_SESSION_WINDOWS);
    const high = pool.find((l) => l.kind === "session_high");
    const low = pool.find((l) => l.kind === "session_low");
    expect(high?.price).toBeCloseTo(1.108);
    expect(low?.price).toBeCloseTo(1.099);
  });

  it("marks a session level swept once a later candle wicks beyond it", () => {
    const withSweep = series(
      [
        ...([
          [1.105, 1.101],
          [1.106, 1.1005],
          [1.1055, 1.102],
          [1.107, 1.099],
          [1.108, 1.1],
          [1.104, 1.101],
          [1.103, 1.1015],
        ] as Array<[number, number]>),
        [1.109, 1.102], // 7 london: high 1.109 > asia high 1.108 -> swept
      ],
      { stepMinutes: 60 },
    );
    const pool = liquidityPool(withSweep, [], 0.3, DEFAULT_SESSION_WINDOWS);
    const high = pool.find((l) => l.kind === "session_high");
    expect(high?.sweptAt).not.toBeNull();
  });
});

describe("opposingTarget / sweepTriggerCandidate", () => {
  const base = { symbol: "EURUSD", timeframe: "M1" as const, detectedAt: "2026-01-05T00:00:00.000Z" };
  const pool: LiquidityLevel[] = [
    { levelId: "a", ...base, kind: "previous_day_high", price: 1.11, sweptAt: null },
    { levelId: "b", ...base, kind: "equal_highs", price: 1.105, sweptAt: null },
    { levelId: "c", ...base, kind: "previous_day_low", price: 1.09, sweptAt: null },
    { levelId: "d", ...base, kind: "equal_lows", price: 1.095, sweptAt: "2026-01-05T01:00:00.000Z" }, // already swept
  ];

  it("buy target is the nearest unswept high-side level", () => {
    // fromPrice 1.10: distances are 1.105 (0.005) vs 1.11 (0.01) -> nearest is equal_highs.
    expect(opposingTarget(pool, "buy", 1.1)).toMatchObject({ kind: "equal_highs", price: 1.105 });
  });

  it("buy sweep trigger is the nearest unswept low-side level, ignoring already-swept ones", () => {
    // equal_lows (1.095) is closer to 1.10 than previous_day_low (1.09) but already swept -> skipped.
    expect(sweepTriggerCandidate(pool, "buy", 1.1)).toMatchObject({ kind: "previous_day_low", price: 1.09 });
  });

  it("returns null when no candidate qualifies", () => {
    const allSwept: LiquidityLevel[] = pool.map((l) => ({ ...l, sweptAt: "2026-01-05T01:00:00.000Z" }));
    expect(opposingTarget(allSwept, "buy", 1.1)).toBeNull();
    expect(sweepTriggerCandidate(allSwept, "sell", 1.1)).toBeNull();
  });
});
