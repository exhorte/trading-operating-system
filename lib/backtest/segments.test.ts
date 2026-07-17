import { describe, expect, it } from "vitest";
import {
  DIMENSIONS,
  MIN_BUCKET_N,
  reportableTrades,
  segmentBy,
  segmentByMulti,
  summarize,
  type DiagTrade,
} from "./segments";

function trade(over: Partial<DiagTrade>): DiagTrade {
  return {
    signalTime: "2026-01-05T13:00:00.000Z", // a Monday
    side: "buy",
    outcome: "win",
    bothTouch: false,
    rMultiple: 2,
    barsHeld: 5,
    score: 6,
    entryPrice: 100,
    stopLoss: 95,
    split: "train",
    features: { session: "london", bias: "bullish", sideVsBias: "with", liqKinds: ["equal_highs"] },
    ...over,
  };
}

describe("OOS lock (headline metrics must never include out-of-sample)", () => {
  // Regression guard: the reporter headline and the runner console both used to
  // aggregate over ALL trades, silently revealing OOS performance while the
  // split was advertised as locked.
  const mixed = [
    ...Array.from({ length: 4 }, () => trade({ split: "train", outcome: "loss", rMultiple: -1 })),
    ...Array.from({ length: 2 }, () => trade({ split: "validation", outcome: "loss", rMultiple: -1 })),
    ...Array.from({ length: 3 }, () => trade({ split: "oos", outcome: "win", rMultiple: 2 })),
  ];

  it("excludes oos trades while locked, and the headline never sees their R", () => {
    const locked = reportableTrades(mixed, false);
    expect(locked).toHaveLength(6);
    expect(locked.every((t) => t.split !== "oos")).toBe(true);

    const headline = summarize("train+validation", locked);
    expect(headline.n).toBe(6);
    expect(headline.cumulativeR).toBe(-6); // not -6 + 6 = 0: the oos wins stay invisible
    expect(headline.winRate).toBe(0);
  });

  it("includes every split once unlocked", () => {
    const unlocked = reportableTrades(mixed, true);
    expect(unlocked).toHaveLength(9);
    expect(summarize("full period", unlocked).cumulativeR).toBe(0); // -6 + 6
  });
});

describe("segmentBy", () => {
  it("groups, computes per-bucket metrics, and sorts worst-first", () => {
    const trades = [
      ...Array.from({ length: 3 }, () => trade({ side: "buy" })), // +2R each
      ...Array.from({ length: 2 }, () => trade({ side: "sell", outcome: "loss", rMultiple: -1 })),
    ];
    const stats = segmentBy(trades, DIMENSIONS.side);
    expect(stats[0].bucket).toBe("sell"); // worst first (loss hunt)
    expect(stats[0].cumulativeR).toBe(-2);
    expect(stats[1]).toMatchObject({ bucket: "buy", n: 3, winRate: 100, cumulativeR: 6 });
  });

  it("flags low-sample buckets as non-informative", () => {
    const stats = segmentBy([trade({})], DIMENSIONS.session);
    expect(stats[0].lowSample).toBe(true);
    const big = segmentBy(Array.from({ length: MIN_BUCKET_N }, () => trade({})), DIMENSIONS.session);
    expect(big[0].lowSample).toBe(false);
  });

  it("derives day-of-week and month from signal time, missing features as '(missing)'", () => {
    const t = trade({ features: {} });
    expect(DIMENSIONS.dayOfWeek(t)).toBe("Mon");
    expect(DIMENSIONS.month(t)).toBe("2026-01");
    expect(DIMENSIONS.session(t)).toBe("(missing)");
  });
});

describe("segmentByMulti", () => {
  it("counts a trade in every kind bucket; empty lists fall into (none)", () => {
    const trades = [
      trade({ features: { liqKinds: ["equal_highs", "previous_day_high"] } }),
      trade({ features: { liqKinds: [] } }),
    ];
    const stats = segmentByMulti(trades, (t) =>
      Array.isArray(t.features.liqKinds) ? (t.features.liqKinds as string[]) : [],
    );
    const buckets = stats.map((s) => s.bucket).sort();
    expect(buckets).toEqual(["(none)", "equal_highs", "previous_day_high"]);
  });
});
