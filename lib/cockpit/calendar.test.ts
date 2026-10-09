import { describe, expect, it } from "vitest";
import { blackoutWindow, inBlackout, listedReleases, nextRelease } from "./calendar";

const release = (id: number, scheduledAt: string) => ({ releaseId: id, label: `R${id}`, scheduledAt });
const NOW = Date.parse("2026-10-09T12:00:00Z");

describe("nextRelease", () => {
  it("is the soonest one at or after now", () => {
    const releases = [release(1, "2026-10-09T14:00:00Z"), release(2, "2026-10-09T12:30:00Z"), release(3, "2026-10-09T11:00:00Z")];
    expect(nextRelease(NOW, releases)?.releaseId).toBe(2);
    expect(nextRelease(NOW, [release(4, "2026-10-09T12:00:00Z")])?.releaseId).toBe(4); // at now counts
  });

  it("is null when none is known, so that 'unknown' is never read as 'nothing scheduled'", () => {
    expect(nextRelease(NOW, [])).toBeNull();
    expect(nextRelease(NOW, [release(1, "2026-10-09T11:59:59Z")])).toBeNull();
  });
});

describe("inBlackout", () => {
  it("is symmetric around the scheduled time and inclusive at the edges", () => {
    const r = release(1, "2026-10-09T12:30:00Z");
    expect(inBlackout(Date.parse("2026-10-09T12:15:00Z"), r, 15)).toBe(true);
    expect(inBlackout(Date.parse("2026-10-09T12:45:00Z"), r, 15)).toBe(true);
    expect(inBlackout(Date.parse("2026-10-09T12:14:59Z"), r, 15)).toBe(false);
    expect(inBlackout(Date.parse("2026-10-09T12:45:01Z"), r, 15)).toBe(false);
  });
});

describe("listedReleases", () => {
  it("keeps a release until its window has ended, soonest first", () => {
    const releases = [release(1, "2026-10-09T13:00:00Z"), release(2, "2026-10-09T11:50:00Z"), release(3, "2026-10-09T11:40:00Z")];
    expect(listedReleases(NOW, releases, 15).map((r) => r.releaseId)).toEqual([2, 1]); // 3 ended at 11:55
  });
});

describe("blackoutWindow", () => {
  it("is the instants either side", () => {
    const [from, to] = blackoutWindow(release(1, "2026-10-09T12:30:00Z"), 10);
    expect(new Date(from).toISOString()).toBe("2026-10-09T12:20:00.000Z");
    expect(new Date(to).toISOString()).toBe("2026-10-09T12:40:00.000Z");
  });
});
