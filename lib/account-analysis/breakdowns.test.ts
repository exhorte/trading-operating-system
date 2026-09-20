import { describe, expect, it } from "vitest";
import type { JournalTrade } from "@/lib/journal/types";
import {
  accountBreakdowns,
  bucketBy,
  durationLabel,
  generalStats,
  mostFrequent,
  tradingDayStats,
  worstBucket,
} from "./breakdowns";

function trade(overrides: Partial<JournalTrade> = {}): JournalTrade {
  return {
    brokerPositionId: "1",
    symbol: "EURUSDm",
    side: "buy",
    volume: 0.1,
    entryPrice: 1.1,
    exitPrice: 1.11,
    realizedPnl: 10,
    stopLoss: 1.09,
    openedAt: "2026-09-14T10:00:00Z",
    closedAt: "2026-09-14T10:01:00Z",
    hasCapture: false,
    ...overrides,
  };
}

describe("bucketBy", () => {
  it("sums trades and P&L per key", () => {
    const buckets = bucketBy(
      [trade({ symbol: "A", realizedPnl: 5 }), trade({ symbol: "A", realizedPnl: -2 }), trade({ symbol: "B" })],
      (t) => t.symbol,
    );
    expect(buckets).toEqual([
      { label: "A", trades: 2, pnl: 3 },
      { label: "B", trades: 1, pnl: 10 },
    ]);
  });

  // A dropped trade must not reappear as an "unknown" bucket whose total
  // silently absorbs it.
  it("drops trades whose key is null rather than pooling them", () => {
    const buckets = bucketBy([trade(), trade({ openedAt: null })], (t) => t.openedAt);
    expect(buckets).toHaveLength(1);
    expect(buckets[0].trades).toBe(1);
  });
});

describe("durationLabel", () => {
  it.each([
    [60, "< 2 min"],
    [200, "2 – 5 min"],
    [600, "5 – 15 min"],
    [2000, "15 – 60 min"],
    [7200, "> 1 h"],
  ])("puts a %i second trade in %s", (seconds, expected) => {
    const closedAt = new Date(Date.parse("2026-09-14T10:00:00Z") + seconds * 1000).toISOString();
    expect(durationLabel(trade({ closedAt }))).toBe(expected);
  });

  it("is null without a recorded opening — unknown, not zero", () => {
    expect(durationLabel(trade({ openedAt: null }))).toBeNull();
  });

  it("is null when the close precedes the open rather than reporting a negative bucket", () => {
    expect(durationLabel(trade({ closedAt: "2026-09-14T09:00:00Z" }))).toBeNull();
  });
});

describe("generalStats", () => {
  it("separates wins, losses and flat trades", () => {
    const stats = generalStats([
      trade({ realizedPnl: 10 }),
      trade({ realizedPnl: 30 }),
      trade({ realizedPnl: -20 }),
      trade({ realizedPnl: 0 }),
    ]);
    expect(stats.tradeCount).toBe(4);
    expect(stats.netPnl).toBe(20);
    expect(stats.wins).toBe(2);
    expect(stats.losses).toBe(1);
    expect(stats.breakeven).toBe(1);
    expect(stats.winRate).toBe(0.5);
    expect(stats.avgWin).toBe(20);
    expect(stats.avgLoss).toBe(-20);
    expect(stats.maxWin).toBe(30);
    expect(stats.maxLoss).toBe(-20);
    expect(stats.rewardRiskRatio).toBe(1);
  });

  // A ratio against zero losing trades is unknown, not infinitely good.
  it("returns a null ratio when one side is missing", () => {
    const stats = generalStats([trade({ realizedPnl: 10 })]);
    expect(stats.avgLoss).toBeNull();
    expect(stats.rewardRiskRatio).toBeNull();
  });

  it("handles an empty period without dividing by zero", () => {
    const stats = generalStats([]);
    expect(stats).toMatchObject({ tradeCount: 0, netPnl: 0, winRate: 0, avgWin: null });
  });
});

describe("tradingDayStats", () => {
  it("groups on the closing date and splits positive from negative days", () => {
    const stats = tradingDayStats([
      trade({ closedAt: "2026-09-14T10:00:00Z", realizedPnl: 10 }),
      trade({ closedAt: "2026-09-14T15:00:00Z", realizedPnl: -30 }),
      trade({ closedAt: "2026-09-15T10:00:00Z", realizedPnl: 40 }),
    ]);
    expect(stats.dayCount).toBe(2);
    expect(stats.avgTradesPerDay).toBe(1.5);
    expect(stats.positiveDays).toBe(1);
    expect(stats.negativeDays).toBe(1);
    expect(stats.avgNegativeDay).toBe(-20);
    expect(stats.bestDay?.label).toBe("2026-09-15");
    expect(stats.worstDay?.label).toBe("2026-09-14");
  });
});

describe("accountBreakdowns", () => {
  // The whole point of keeping both readings: a trade crossing midnight
  // belongs to a different weekday depending on the question.
  it("reads opening day and closing day separately", () => {
    const { byOpenDay, byCloseDay } = accountBreakdowns([
      trade({ openedAt: "2026-09-14T23:30:00Z", closedAt: "2026-09-15T00:30:00Z" }),
    ]);
    expect(byOpenDay[0].label).toBe("Lundi");
    expect(byCloseDay[0].label).toBe("Mardi");
  });

  it("orders duration buckets chronologically, not by frequency", () => {
    const { byDuration } = accountBreakdowns([
      trade({ closedAt: "2026-09-14T10:30:00Z" }),
      trade({ closedAt: "2026-09-14T10:00:30Z" }),
      trade({ closedAt: "2026-09-14T10:00:30Z" }),
    ]);
    expect(byDuration.map((b) => b.label)).toEqual(["< 2 min", "15 – 60 min"]);
  });

  it("orders position sizes numerically, not as strings", () => {
    const { bySize } = accountBreakdowns([
      trade({ volume: 0.2 }),
      trade({ volume: 1.5 }),
      trade({ volume: 0.1 }),
    ]);
    expect(bySize.map((b) => b.label)).toEqual(["0.10", "0.20", "1.50"]);
  });

  it("labels sides in the interface's language", () => {
    const { bySide } = accountBreakdowns([trade({ side: "buy" }), trade({ side: "sell" })]);
    expect(bySide.map((b) => b.label).sort()).toEqual(["Achat", "Vente"]);
  });
});

describe("mostFrequent / worstBucket", () => {
  it("picks the fullest bucket and the costliest one independently", () => {
    const buckets = [
      { label: "a", trades: 5, pnl: -10 },
      { label: "b", trades: 1, pnl: -80 },
    ];
    expect(mostFrequent(buckets)?.label).toBe("a");
    expect(worstBucket(buckets)?.label).toBe("b");
  });

  it("has no worst bucket when nothing lost money", () => {
    expect(worstBucket([{ label: "a", trades: 2, pnl: 5 }])).toBeNull();
  });

  it("has no most-frequent bucket in an empty breakdown", () => {
    expect(mostFrequent([])).toBeNull();
  });
});
