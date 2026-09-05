/**
 * T03 — pure calendar logic for the news gate. The whitelist of FRED
 * releases IS the impact classification (context/product/tools/T03-gate-news.md);
 * this module never asks "how important is this release", only "is now
 * inside the blackout window around one of them".
 *
 * Deliberately symmetric: the card's "−30 / +30 minutes" window means the
 * SAME magnitude on both sides of the scheduled time, driven by the single
 * configured `policy.newsBlackoutMinutes` (lib/domain/risk.ts).
 */

import type { UtcTimestamp } from "@/lib/domain/primitives";
import type { UpcomingRelease } from "@/lib/domain/risk";

export type { UpcomingRelease };

export function isNewsBlackout(
  now: UtcTimestamp,
  releases: UpcomingRelease[],
  windowMinutes: number,
): boolean {
  const nowMs = Date.parse(now);
  const windowMs = windowMinutes * 60_000;
  return releases.some((release) => Math.abs(Date.parse(release.scheduledAt) - nowMs) <= windowMs);
}

/** The soonest release at or after `now`, or null when none is known —
 *  callers must not confuse "none known" with "none scheduled". */
export function nextRelease(now: UtcTimestamp, releases: UpcomingRelease[]): UpcomingRelease | null {
  const nowMs = Date.parse(now);
  let soonest: UpcomingRelease | null = null;
  for (const release of releases) {
    if (Date.parse(release.scheduledAt) < nowMs) {
      continue;
    }
    if (soonest === null || Date.parse(release.scheduledAt) < Date.parse(soonest.scheduledAt)) {
      soonest = release;
    }
  }
  return soonest;
}
