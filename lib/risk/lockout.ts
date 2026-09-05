/**
 * T02a — the lockout ledger is the source of truth for "locked right now,"
 * never re-derived purely from live gate evaluation (a missing event or a
 * shifted day boundary could otherwise silently undo it). These are the
 * pure decision points around that ledger; the caller (mock-client.ts /
 * signalr-client.ts) owns publishing and persistence.
 */

import type { RiskState } from "@/lib/domain/risk";
import type { UtcTimestamp } from "@/lib/domain/primitives";

export const KILL_SWITCH_REASON = "Kill switch manuel";

export const CONSECUTIVE_LOSS_REASON = "Pertes consécutives";

/** T02b: forced pause length after the configured number of consecutive losses. */
export const CONSECUTIVE_LOSS_PAUSE_MINUTES = 30;

export interface ActiveLockout {
  lockoutId: string;
  reason: string;
  since: UtcTimestamp;
  /** Null = manual/next-day clearance required. Set = auto-expires (T02b). */
  until: UtcTimestamp | null;
}

/**
 * Edge-triggered: only fires the moment a freshly-computed state crosses
 * into "locked" while no lockout is already on record — never on every
 * evaluation while already locked, which would spam duplicate ledger rows.
 */
export function detectNewLockout(
  state: RiskState,
  activeLockout: ActiveLockout | null,
): { reason: string } | null {
  if (state.mode !== "locked" || activeLockout !== null) {
    return null;
  }
  return { reason: state.lockoutReason ?? "locked" };
}

/** T02b: an auto-expiring pause (until !== null) whose clock has run out.
 *  A manual/next-day lockout (until === null) is never "expired" this way. */
export function isLockoutExpired(activeLockout: ActiveLockout, now: UtcTimestamp): boolean {
  return activeLockout.until !== null && Date.parse(activeLockout.until) <= Date.parse(now);
}

/**
 * The ledger overrides live computation whenever it says locked: even if
 * gates recover on their own (e.g. equity ticks back up before the day
 * anchor rolls over), the stored lock still holds until cleared. T02b: an
 * expired timed pause is the one exception — the state passes through
 * unchanged (never forced to "locked"), but the caller is still responsible
 * for publishing risk.lockout.cleared so the ledger doesn't keep a stale row
 * (see isLockoutExpired).
 */
export function applyActiveLockout(
  state: RiskState,
  activeLockout: ActiveLockout | null,
  now: UtcTimestamp,
): RiskState {
  if (!activeLockout || isLockoutExpired(activeLockout, now)) {
    return state;
  }
  return {
    ...state,
    mode: "locked",
    lockoutReason: activeLockout.reason,
    lockoutUntil: activeLockout.until,
  };
}

/**
 * T02b: the second hard lockout source, kept separate from detectNewLockout
 * (different semantics — this one computes an `until`). Fires only on the
 * specific consecutive-loss gate breach, edge-triggered like detectNewLockout
 * (no re-fire while a lockout — of any reason — is already on record, so a
 * further loss during the pause does not extend it).
 */
export function detectConsecutiveLossPause(
  state: RiskState,
  activeLockout: ActiveLockout | null,
  lastConsecutiveLossAt: UtcTimestamp | null,
  pauseMinutes: number,
): { reason: string; until: UtcTimestamp } | null {
  if (activeLockout !== null || lastConsecutiveLossAt === null) {
    return null;
  }
  const consecutiveGate = state.gates.find((g) => g.gateId === "gate-consec-loss");
  if (!consecutiveGate || consecutiveGate.state !== "blocked") {
    return null;
  }
  return {
    reason: CONSECUTIVE_LOSS_REASON,
    until: new Date(Date.parse(lastConsecutiveLossAt) + pauseMinutes * 60_000).toISOString(),
  };
}

/**
 * Daily-loss and max-trades lockouts are pure calendar locks: a new trading
 * day releases them automatically. The kill switch is deliberately not —
 * it requires an explicit acknowledgment (RiskLockoutAcknowledgedPayload),
 * never a day rollover, because the entire point is the trader certifying
 * "I actually closed my positions," not a timer doing it for them.
 */
export function shouldAutoClearForNewDay(
  activeLockout: ActiveLockout,
  dayAnchorStartsAtUtc: UtcTimestamp,
): boolean {
  return (
    activeLockout.reason !== KILL_SWITCH_REASON &&
    Date.parse(activeLockout.since) < Date.parse(dayAnchorStartsAtUtc)
  );
}
