/**
 * Virgin holdout declaration and lock helpers (Phase 13). Pure.
 *
 * The anterior window below was NEVER imported or consulted — it is the frozen
 * candidate's single remaining verdict. The lock is enforced by construction:
 * the runner CLIPS holdout candles out of every ordinary run and refuses runs
 * that lie entirely inside; only the one-shot --verdict-holdout mode may read
 * them, and the DB's holdout_verdicts primary key makes that read unique.
 *
 * Boundaries fixed by the user 2026-07-18 (UTC, no overlap with the dev set):
 * start INCLUSIVE 2024-06-01T00:00:00Z; end EXCLUSIVE 2025-06-06T13:30:00Z —
 * the development dataset's first candle opens exactly at the exclusive end.
 */

import type { Candle } from "@/lib/domain/market";

export const VIRGIN_HOLDOUT = {
  symbol: "XAUUSDm",
  timeframe: "M15",
  /** Inclusive. */
  fromUtc: "2024-06-01T00:00:00.000Z",
  /** Exclusive — the dev dataset's first candle (2025-06-06T13:30Z) is out. */
  toUtc: "2025-06-06T13:30:00.000Z",
} as const;

const FROM_MS = Date.parse(VIRGIN_HOLDOUT.fromUtc);
const TO_MS = Date.parse(VIRGIN_HOLDOUT.toUtc);

/** A candle open time inside [from, to) belongs to the holdout. */
export function isHoldoutTime(openTimeIso: string): boolean {
  const t = Date.parse(openTimeIso);
  return t >= FROM_MS && t < TO_MS;
}

/** Ordinary runs: remove every holdout candle. Returns the clipped series and
 *  how many candles were removed (for the loud warning). */
export function clipHoldout(candles: Candle[]): { kept: Candle[]; removed: number } {
  const kept = candles.filter((c) => !isHoldoutTime(c.openTime));
  return { kept, removed: candles.length - kept.length };
}

/** Verdict mode: keep ONLY holdout candles. */
export function onlyHoldout(candles: Candle[]): Candle[] {
  return candles.filter((c) => isHoldoutTime(c.openTime));
}
