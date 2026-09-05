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

/**
 * The ledger overrides live computation whenever it says locked: even if
 * gates recover on their own (e.g. equity ticks back up before the day
 * anchor rolls over), the stored lock still holds until cleared.
 */
export function applyActiveLockout(state: RiskState, activeLockout: ActiveLockout | null): RiskState {
  if (!activeLockout) {
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
