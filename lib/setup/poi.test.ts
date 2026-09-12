import { describe, expect, it } from "vitest";
import { isInvalidatedByCe, pointOfInterestFor } from "./poi";
import { series } from "@/lib/analysis/test-helpers";
import type { DisplacementEvent } from "./displacement";
import type { OrderBlock } from "@/lib/domain/analysis";

const base = { symbol: "EURUSD", timeframe: "M1" as const };

function displacementWith(mitigatedAt: string | null): DisplacementEvent {
  return {
    occurredAt: "2026-01-05T00:03:00.000Z",
    brokenSwingPrice: 103,
    fairValueGap: {
      fvgId: "fvg-3",
      ...base,
      direction: "bullish",
      high: 102.8,
      low: 102,
      filledPercent: mitigatedAt ? 100 : 0,
      mitigatedAt,
      detectedAt: "2026-01-05T00:03:00.000Z",
    },
    bodySize: 7,
    atr: 3.5,
  };
}

describe("pointOfInterestFor", () => {
  it("uses the FVG when it is not yet mitigated", () => {
    const poi = pointOfInterestFor(displacementWith(null), [], "buy");
    expect(poi).toMatchObject({ kind: "fvg", high: 102.8, low: 102, ce: 102.4 });
  });

  it("falls back to the origin order block when the FVG is already mitigated", () => {
    const orderBlocks: OrderBlock[] = [
      {
        orderBlockId: "ob-1",
        ...base,
        direction: "bullish",
        high: 101,
        low: 100.5,
        mitigatedAt: null,
        detectedAt: "2026-01-05T00:00:00.000Z", // before the displacement
      },
    ];
    const poi = pointOfInterestFor(displacementWith("2026-01-05T00:04:00.000Z"), orderBlocks, "buy");
    expect(poi).toMatchObject({ kind: "order_block", high: 101, low: 100.5, ce: 100.75 });
  });

  it("returns null when the FVG is mitigated and no usable order block exists", () => {
    expect(pointOfInterestFor(displacementWith("2026-01-05T00:04:00.000Z"), [], "buy")).toBeNull();
  });
});

describe("isInvalidatedByCe", () => {
  const poi = { kind: "fvg" as const, high: 102.8, low: 102, ce: 102.4, formedAt: "2026-01-05T00:03:00.000Z" };

  it("is invalidated once a candle body closes beyond the CE (buy side: below it)", () => {
    const candles = series([
      { high: 102.6, low: 102.3, close: 102.5 }, // still above CE
      { high: 102.4, low: 102.1, close: 102.2 }, // body closes below CE 102.4 -> invalidated
    ]);
    expect(isInvalidatedByCe(poi, "buy", candles)).toBe(true);
  });

  it("is not invalidated while every body close stays on the right side of the CE", () => {
    const candles = series([
      { high: 102.7, low: 102.45, close: 102.5 },
      { high: 102.6, low: 102.41, close: 102.45 },
    ]);
    expect(isInvalidatedByCe(poi, "buy", candles)).toBe(false);
  });
});
