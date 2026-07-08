/**
 * Session bucketing: map a UTC timestamp to an ICT trading session using the
 * configured windows. Windows may wrap midnight (e.g. Asia 23:00–07:00).
 */

import type { SessionWindow } from "@/lib/domain/market";
import type { TradingSession, UtcTimestamp } from "@/lib/domain/primitives";

function minutesOfDay(hhmm: string): number {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

function contains(window: SessionWindow, minutes: number): boolean {
  const start = minutesOfDay(window.startUtc);
  const end = minutesOfDay(window.endUtc);
  // Non-wrapping window: [start, end).
  if (start <= end) {
    return minutes >= start && minutes < end;
  }
  // Wrapping window (crosses midnight): [start, 24:00) ∪ [00:00, end).
  return minutes >= start || minutes < end;
}

export function sessionForTimestamp(
  ts: UtcTimestamp,
  windows: SessionWindow[],
): TradingSession {
  const d = new Date(ts);
  const minutes = d.getUTCHours() * 60 + d.getUTCMinutes();
  const hit = windows.find((w) => contains(w, minutes));
  return hit ? hit.session : "off_session";
}

export function sessionEnabled(
  session: TradingSession,
  windows: SessionWindow[],
): boolean {
  return windows.find((w) => w.session === session)?.tradingEnabled ?? false;
}
