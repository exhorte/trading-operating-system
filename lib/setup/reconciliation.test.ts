import { describe, expect, it } from "vitest";
import { reconcile } from "./reconciliation";

describe("reconcile", () => {
  it("classifies a trade opened within tolerance of a proposal as PROPOSE_ET_PRIS", () => {
    const rows = reconcile(
      [{ symbol: "EURUSDm", side: "buy", detectedAt: "2026-01-05T10:00:00.000Z" }],
      [{ brokerPositionId: "p1", symbol: "EURUSDm", side: "buy", openedAt: "2026-01-05T10:03:00.000Z" }],
      5,
    );
    expect(rows).toEqual([
      {
        class: "PROPOSE_ET_PRIS",
        symbol: "EURUSDm",
        side: "buy",
        proposalDetectedAt: "2026-01-05T10:00:00.000Z",
        tradeOpenedAt: "2026-01-05T10:03:00.000Z",
        brokerPositionId: "p1",
      },
    ]);
  });

  it("classifies a proposal with no matching trade as PROPOSE_ET_REFUSE", () => {
    const rows = reconcile(
      [{ symbol: "EURUSDm", side: "buy", detectedAt: "2026-01-05T10:00:00.000Z" }],
      [],
      5,
    );
    expect(rows).toEqual([
      {
        class: "PROPOSE_ET_REFUSE",
        symbol: "EURUSDm",
        side: "buy",
        proposalDetectedAt: "2026-01-05T10:00:00.000Z",
        tradeOpenedAt: null,
        brokerPositionId: null,
      },
    ]);
  });

  it("classifies a trade with no matching proposal as PRIS_SANS_PROPOSITION — the most important case", () => {
    const rows = reconcile(
      [],
      [{ brokerPositionId: "p1", symbol: "GBPUSDm", side: "sell", openedAt: "2026-01-05T10:00:00.000Z" }],
      5,
    );
    expect(rows).toEqual([
      {
        class: "PRIS_SANS_PROPOSITION",
        symbol: "GBPUSDm",
        side: "sell",
        proposalDetectedAt: null,
        tradeOpenedAt: "2026-01-05T10:00:00.000Z",
        brokerPositionId: "p1",
      },
    ]);
  });

  it("does not match across symbols, sides, or outside the tolerance window", () => {
    const proposal = { symbol: "EURUSDm", side: "buy" as const, detectedAt: "2026-01-05T10:00:00.000Z" };
    const wrongSymbol = { brokerPositionId: "a", symbol: "GBPUSDm", side: "buy" as const, openedAt: "2026-01-05T10:01:00.000Z" };
    const wrongSide = { brokerPositionId: "b", symbol: "EURUSDm", side: "sell" as const, openedAt: "2026-01-05T10:01:00.000Z" };
    const tooLate = { brokerPositionId: "c", symbol: "EURUSDm", side: "buy" as const, openedAt: "2026-01-05T10:10:00.000Z" };

    const rows = reconcile([proposal], [wrongSymbol, wrongSide, tooLate], 5);
    expect(rows.filter((r) => r.class === "PROPOSE_ET_PRIS")).toHaveLength(0);
    expect(rows.filter((r) => r.class === "PRIS_SANS_PROPOSITION")).toHaveLength(3);
  });

  it("matches each trade to at most one proposal — the nearest one, and only once", () => {
    const proposals = [
      { symbol: "EURUSDm", side: "buy" as const, detectedAt: "2026-01-05T10:00:00.000Z" },
      { symbol: "EURUSDm", side: "buy" as const, detectedAt: "2026-01-05T10:01:00.000Z" },
    ];
    // Only one trade — closer to the second proposal.
    const trades = [{ brokerPositionId: "p1", symbol: "EURUSDm", side: "buy" as const, openedAt: "2026-01-05T10:01:30.000Z" }];

    const rows = reconcile(proposals, trades, 5);
    const pris = rows.filter((r) => r.class === "PROPOSE_ET_PRIS");
    expect(pris).toHaveLength(1);
    expect(pris[0].proposalDetectedAt).toBe("2026-01-05T10:01:00.000Z");
    expect(rows.filter((r) => r.class === "PROPOSE_ET_REFUSE")).toHaveLength(1);
    expect(rows.filter((r) => r.class === "PRIS_SANS_PROPOSITION")).toHaveLength(0);
  });
});
