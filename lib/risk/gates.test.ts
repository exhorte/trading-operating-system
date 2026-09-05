import { describe, expect, it } from "vitest";
import { newsGate } from "./gates";
import { defaultRiskPolicy } from "./policy";
import type { UpcomingRelease } from "./news-calendar";

const policy = defaultRiskPolicy("acc-1");
const NOW = "2026-09-05T13:30:00.000Z";

// T03-gate-news.md: "en cas de données absentes, la gate refuse" — the one
// behavior in this file that MUST NOT regress to fail-open.
describe("newsGate — fail-closed on missing data", () => {
  it("blocks when releases is null (cache never hydrated / FRED unreachable / bad key)", () => {
    const gate = newsGate(null, NOW, policy);
    expect(gate.state).toBe("blocked");
    expect(gate.detail).toMatch(/no calendar data/i);
  });

  it("does NOT treat an empty (but known) calendar the same as absent data", () => {
    const gate = newsGate([], NOW, policy);
    expect(gate.state).toBe("open");
  });
});

describe("newsGate — blackout window", () => {
  const cpi: UpcomingRelease = { releaseId: 10, label: "CPI US", scheduledAt: "2026-09-05T14:00:00.000Z" };

  it("blocks inside the policy's configured window", () => {
    const gate = newsGate([cpi], "2026-09-05T13:45:00.000Z", policy);
    expect(gate.state).toBe("blocked");
  });

  it("stays open outside the window and reports the next release", () => {
    const gate = newsGate([cpi], "2026-09-05T10:00:00.000Z", policy);
    expect(gate.state).toBe("open");
    expect(gate.detail).toContain("CPI US");
  });

  it("uses policy.newsBlackoutMinutes, never a hardcoded value", () => {
    const tightPolicy = { ...policy, newsBlackoutMinutes: 5 };
    // 15 minutes out: blocked under the default 30min policy, open under 5min.
    const soon = { ...cpi, scheduledAt: "2026-09-05T13:45:00.000Z" };
    expect(newsGate([soon], NOW, policy).state).toBe("blocked");
    expect(newsGate([soon], NOW, tightPolicy).state).toBe("open");
  });
});
