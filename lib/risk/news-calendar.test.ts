import { describe, expect, it } from "vitest";
import { isNewsBlackout, nextRelease, type UpcomingRelease } from "./news-calendar";

const NOW = "2026-09-05T13:30:00.000Z";

const cpi: UpcomingRelease = { releaseId: 10, label: "CPI US", scheduledAt: "2026-09-05T14:00:00.000Z" };
const fomc: UpcomingRelease = { releaseId: 101, label: "FOMC", scheduledAt: "2026-09-17T18:00:00.000Z" };

describe("isNewsBlackout", () => {
  it("is false when nothing is within the window", () => {
    // CPI at 14:00 is 60min from 13:00 — clear of the ±30min window.
    expect(isNewsBlackout("2026-09-05T13:00:00.000Z", [cpi, fomc], 30)).toBe(false);
  });

  it("is true exactly at the window edge (inclusive)", () => {
    expect(isNewsBlackout(NOW, [cpi], 30)).toBe(true); // CPI is exactly 30min away
  });

  it("is true inside the window before a release", () => {
    expect(isNewsBlackout("2026-09-05T13:45:00.000Z", [cpi], 30)).toBe(true); // 15min before
  });

  it("is true inside the window after a release (symmetric −30/+30)", () => {
    expect(isNewsBlackout("2026-09-05T14:15:00.000Z", [cpi], 30)).toBe(true); // 15min after
  });

  it("is false just outside the window", () => {
    expect(isNewsBlackout("2026-09-05T14:31:00.000Z", [cpi], 30)).toBe(false); // 31min after
  });

  it("is false with an empty release list", () => {
    expect(isNewsBlackout(NOW, [], 30)).toBe(false);
  });
});

describe("nextRelease", () => {
  it("returns the soonest release at or after now, ignoring past ones", () => {
    const past: UpcomingRelease = { releaseId: 9, label: "Retail Sales US", scheduledAt: "2026-09-01T12:30:00.000Z" };
    expect(nextRelease(NOW, [fomc, past, cpi])).toEqual(cpi);
  });

  it("returns null when there is nothing upcoming", () => {
    expect(nextRelease(NOW, [])).toBeNull();
  });

  it("returns null when every known release is already in the past", () => {
    const past: UpcomingRelease = { releaseId: 9, label: "Retail Sales US", scheduledAt: "2026-09-01T12:30:00.000Z" };
    expect(nextRelease(NOW, [past])).toBeNull();
  });
});
