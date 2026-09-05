import { describe, expect, it } from "vitest";
import { sessionEnabled, sessionForTimestamp } from "./sessions";
import { DEFAULT_SESSION_WINDOWS } from "./config";

const at = (hh: number) => `2026-01-05T${String(hh).padStart(2, "0")}:00:00.000Z`;

describe("sessionForTimestamp", () => {
  it("maps UTC hours to the configured session, including the wrapping Asia window", () => {
    expect(sessionForTimestamp(at(1), DEFAULT_SESSION_WINDOWS)).toBe("asia");
    expect(sessionForTimestamp(at(8), DEFAULT_SESSION_WINDOWS)).toBe("london");
    expect(sessionForTimestamp(at(13), DEFAULT_SESSION_WINDOWS)).toBe("new_york_am");
    expect(sessionForTimestamp(at(17), DEFAULT_SESSION_WINDOWS)).toBe("new_york_pm");
    expect(sessionForTimestamp(at(21), DEFAULT_SESSION_WINDOWS)).toBe("off_session");
  });
});

describe("sessionEnabled", () => {
  it("reflects the tradingEnabled flag of each window", () => {
    expect(sessionEnabled("london", DEFAULT_SESSION_WINDOWS)).toBe(true);
    expect(sessionEnabled("asia", DEFAULT_SESSION_WINDOWS)).toBe(false);
  });
});
