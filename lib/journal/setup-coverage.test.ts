import { describe, expect, it } from "vitest";
import { STRATEGY_MAX_LOOKBACK_DAYS } from "@/lib/api/generated";
import { setupCoverage, setupShare, type CoverableTrade, type SetupContext } from "./setup-coverage";

const DAY = 86_400_000;
const NOW = Date.parse("2026-10-09T19:47:38.000Z");

describe("setupCoverage", () => {
  it("keeps the period's own start when the core can answer that far back", () => {
    const start = "2026-09-20T00:00:00.000Z";
    expect(setupCoverage(start, NOW)).toEqual({ since: start, truncated: false });
  });

  it("starts later, and says so, when the period reaches further back than the core answers for", () => {
    const coverage = setupCoverage("2026-07-11T00:00:00.000Z", NOW); // the journal's 90-day default
    expect(coverage.truncated).toBe(true);
    expect(coverage.since).toBe("2026-09-09T19:00:00.000Z"); // 30 days before NOW, down to the hour
  });

  it("never asks for more than the core's cap, whatever the minute it is asked at", () => {
    for (let minutes = 0; minutes < 24 * 60; minutes += 7) {
      const now = NOW + minutes * 60_000;
      const asked = Date.parse(setupCoverage("2026-01-01T00:00:00.000Z", now).since);
      expect(now - asked).toBeLessThan(STRATEGY_MAX_LOOKBACK_DAYS * DAY);
    }
  });

  it("asks the same question for the whole hour, so a screen left open does not re-ask at every tick", () => {
    const first = setupCoverage("2026-01-01T00:00:00.000Z", Date.parse("2026-10-09T19:00:01.000Z"));
    const later = setupCoverage("2026-01-01T00:00:00.000Z", Date.parse("2026-10-09T19:59:59.000Z"));
    expect(later).toEqual(first);
    const nextHour = setupCoverage("2026-01-01T00:00:00.000Z", Date.parse("2026-10-09T20:00:01.000Z"));
    expect(nextHour.since).not.toBe(first.since);
  });

  it("leaves a start it cannot read alone rather than inventing one", () => {
    expect(setupCoverage("not a date", NOW)).toEqual({ since: "not a date", truncated: false });
  });
});

describe("setupShare", () => {
  const ready: SetupContext = { status: "ready", since: "2026-09-09T19:00:00.000Z", truncated: true };
  const trade = (openedAt: string | null, proposed: boolean, closedAt = "2026-10-01T10:00:00.000Z"): CoverableTrade => ({
    openedAt,
    closedAt,
    proposed,
  });

  it("counts, among the trades the context covers, those that coincided with a proposal", () => {
    const trades = [
      trade("2026-10-01T09:00:00.000Z", true),
      trade("2026-10-02T09:00:00.000Z", false),
      trade("2026-10-03T09:00:00.000Z", true),
    ];
    expect(setupShare(trades, ready)).toEqual({ proposed: 2, of: 3 });
  });

  it("leaves out a trade opened before the context starts: it is neither taken on a proposal nor without one", () => {
    const trades = [trade("2026-08-01T09:00:00.000Z", false, "2026-08-01T10:00:00.000Z"), trade("2026-10-01T09:00:00.000Z", true)];
    expect(setupShare(trades, ready)).toEqual({ proposed: 1, of: 1 });
  });

  it("judges a trade whose opening was never recorded by its closing", () => {
    expect(setupShare([trade(null, false, "2026-10-01T10:00:00.000Z")], ready)).toEqual({ proposed: 0, of: 1 });
    expect(setupShare([trade(null, false, "2026-08-01T10:00:00.000Z")], ready)).toBeNull();
  });

  it("says nothing — a dash, not a zero — while the context is loading, when it could not be read, or when it covers no trade", () => {
    const trades = [trade("2026-10-01T09:00:00.000Z", true)];
    expect(setupShare(trades, { status: "loading" })).toBeNull();
    expect(setupShare(trades, { status: "unavailable" })).toBeNull();
    expect(setupShare([], ready)).toBeNull();
  });
});
