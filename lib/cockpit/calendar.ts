/**
 * How the cockpit *shows* the economic calendar. Display only.
 *
 * The news gate — whether an entry is allowed — is the Risk Engine's, in the core, and it reaches the screen as a gate in the
 * risk status (`risk.gates`). What lives here is the arithmetic a list needs to label its rows: which release is next, which
 * rows are inside their blackout window, what that window is. The window is the account's own rule
 * (`riskProfile.news.blackoutMinutes`); it is passed in, never assumed. Deliberately symmetric, like the gate: the same number
 * of minutes before and after the scheduled time.
 *
 * `null` for the list of releases means *unknown* (the calendar was never synced) and is not a calendar with nothing in it.
 */

import type { UpcomingRelease } from "@/lib/api/generated";

const MINUTE_MS = 60_000;

/** The soonest release at or after `nowMs`, or null when none is known — callers must not confuse "none known" with "none scheduled". */
export function nextRelease(nowMs: number, releases: readonly UpcomingRelease[]): UpcomingRelease | null {
  let soonest: UpcomingRelease | null = null;
  for (const release of releases) {
    const at = Date.parse(release.scheduledAt);
    if (at < nowMs) {
      continue;
    }
    if (soonest === null || at < Date.parse(soonest.scheduledAt)) {
      soonest = release;
    }
  }
  return soonest;
}

/** Whether `nowMs` is within `windowMinutes` of the release, either side. */
export function inBlackout(nowMs: number, release: UpcomingRelease, windowMinutes: number): boolean {
  return Math.abs(Date.parse(release.scheduledAt) - nowMs) <= windowMinutes * MINUTE_MS;
}

/** The releases still worth listing: those whose blackout window has not yet ended, soonest first. */
export function listedReleases(
  nowMs: number,
  releases: readonly UpcomingRelease[],
  windowMinutes: number,
): UpcomingRelease[] {
  return releases
    .filter((release) => Date.parse(release.scheduledAt) + windowMinutes * MINUTE_MS > nowMs)
    .sort((a, b) => Date.parse(a.scheduledAt) - Date.parse(b.scheduledAt));
}

/** `[from, to]` of the blackout around a release, as instants. */
export function blackoutWindow(release: UpcomingRelease, windowMinutes: number): [number, number] {
  const at = Date.parse(release.scheduledAt);
  return [at - windowMinutes * MINUTE_MS, at + windowMinutes * MINUTE_MS];
}
