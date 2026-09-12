/**
 * S01 pre-conditions that have no existing implementation to reuse: the
 * killzone windows and the NY lunch cutoff, both stated in New York local
 * time (DST-aware — via Intl, no new dependency). Everything else in S01's
 * "Pré-conditions" (calendar, lockouts) is read directly from Postgres by
 * the EA-02 worker; nothing here duplicates that.
 *
 * The killzone hour ranges below are ICT-standard values, POSED not
 * derived — the same status as S01's cost threshold (0.25): provisional
 * until an observation sample says otherwise. Neither S01 nor
 * context/domain/ict_smc_framework.md gives numeric hours for them.
 */

import type { UtcTimestamp } from "@/lib/domain/primitives";

const NY_TIME_ZONE = "America/New_York";

/** [startMinute, endMinute) of the New York day, per killzone. */
const KILLZONE_WINDOWS_NY_MINUTES: Record<string, [number, number]> = {
  london: [2 * 60, 5 * 60], // 02:00-05:00 NY
  new_york_am: [7 * 60, 10 * 60], // 07:00-10:00 NY
};

/** S01: "Aucune nouvelle position après 12:00 NY." */
const NY_LUNCH_MINUTE = 12 * 60;

function nyMinutesOfDay(timestamp: UtcTimestamp): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: NY_TIME_ZONE,
    hour: "numeric",
    minute: "numeric",
    hour12: false,
  }).formatToParts(new Date(timestamp));
  const hour = Number(parts.find((p) => p.type === "hour")?.value ?? "0") % 24;
  const minute = Number(parts.find((p) => p.type === "minute")?.value ?? "0");
  return hour * 60 + minute;
}

/** True during the London or New York AM killzone, in New York local time. */
export function isInKillzone(timestamp: UtcTimestamp): boolean {
  const minutes = nyMinutesOfDay(timestamp);
  return Object.values(KILLZONE_WINDOWS_NY_MINUTES).some(([start, end]) => minutes >= start && minutes < end);
}

/** True at/after 12:00 New York time — no new position, per S01. */
export function isPastNyLunch(timestamp: UtcTimestamp): boolean {
  return nyMinutesOfDay(timestamp) >= NY_LUNCH_MINUTE;
}
