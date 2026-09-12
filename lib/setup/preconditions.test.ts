import { describe, expect, it } from "vitest";
import { isInKillzone, isPastNyLunch } from "./preconditions";

describe("isInKillzone", () => {
  it("is true inside the London killzone in winter (EST, UTC-5)", () => {
    // 2026-01-15 is standard time: 03:00 NY = 08:00 UTC.
    expect(isInKillzone("2026-01-15T08:00:00.000Z")).toBe(true);
  });

  it("is true inside the NY AM killzone in summer (EDT, UTC-4) — DST handled", () => {
    // 2026-06-15 is daylight time: 08:00 NY = 12:00 UTC.
    expect(isInKillzone("2026-06-15T12:00:00.000Z")).toBe(true);
  });

  it("is false between the two killzones", () => {
    // 06:00 NY (winter) sits between London (ends 05:00) and NY AM (starts 07:00).
    expect(isInKillzone("2026-01-15T11:00:00.000Z")).toBe(false);
  });

  it("is false outside both killzones (evening)", () => {
    expect(isInKillzone("2026-01-15T23:00:00.000Z")).toBe(false);
  });
});

describe("isPastNyLunch", () => {
  it("is false before 12:00 NY", () => {
    expect(isPastNyLunch("2026-01-15T16:59:00.000Z")).toBe(false); // 11:59 NY (winter)
  });

  it("is true at and after 12:00 NY", () => {
    expect(isPastNyLunch("2026-01-15T17:00:00.000Z")).toBe(true); // 12:00 NY (winter)
    expect(isPastNyLunch("2026-01-15T23:00:00.000Z")).toBe(true); // 18:00 NY (winter)
  });

  it("accounts for DST in summer", () => {
    expect(isPastNyLunch("2026-06-15T16:00:00.000Z")).toBe(true); // 12:00 NY (summer)
    expect(isPastNyLunch("2026-06-15T15:59:00.000Z")).toBe(false); // 11:59 NY (summer)
  });
});
