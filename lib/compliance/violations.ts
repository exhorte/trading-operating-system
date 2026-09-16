/**
 * T07 — pure, closed-taxonomy violation detection. Each function answers one
 * question about one already-closed trade; none of them decide anything
 * live (that's the Risk Engine, lib/risk/, ADR 0007) — this is review,
 * after the fact, exactly like ADR 0005 scopes AI: classify, never order.
 *
 * Only two violation types ship with data behind them today (lockout,
 * session window) — see the fiche for why "stop moved after entry" has no
 * detector here at all (nothing traces position modifications) and why
 * size-policy does NOT reuse lib/risk/sizing.ts::evaluateSignalRisk (that
 * formula hardcodes the XAUUSD tick factor).
 */

import type { SymbolMetadata } from "@/lib/domain/market";
import type { SessionWindow } from "@/lib/domain/market";
import type { RiskPolicy } from "@/lib/domain/risk";
import type { UtcTimestamp } from "@/lib/domain/primitives";
import { sessionForTimestamp, sessionEnabled } from "@/lib/analysis/sessions";

export type ViolationType = "LOCKOUT_ACTIVE" | "SESSION_WINDOW" | "SIZE_POLICY";

export interface Violation {
  type: ViolationType;
  detail: string;
}

export interface LockoutWindow {
  lockoutId: string;
  reason: string;
  since: UtcTimestamp;
  /** Null = requires manual/next-day clearance (never auto-expires). */
  until: UtcTimestamp | null;
  /** Null = still active as of whenever this window was fetched. */
  clearedAt: UtcTimestamp | null;
}

/**
 * Was any lockout active at openedAt? Generalizes RiskTodayRepository's live
 * query (`cleared_at IS NULL AND (until IS NULL OR until > now())`) from
 * "now" to an arbitrary historical instant: a lockout is active at T when it
 * had already started, had not yet been cleared, and had not yet
 * auto-expired, all evaluated AT T — not against the lockout's present-day
 * state.
 */
export function detectLockoutViolation(
  openedAt: UtcTimestamp,
  lockouts: LockoutWindow[],
): Violation | null {
  const openedAtMs = Date.parse(openedAt);
  const active = lockouts.find((l) => {
    if (Date.parse(l.since) > openedAtMs) {
      return false;
    }
    if (l.clearedAt !== null && Date.parse(l.clearedAt) <= openedAtMs) {
      return false;
    }
    if (l.until !== null && Date.parse(l.until) <= openedAtMs) {
      return false;
    }
    return true;
  });
  return active
    ? { type: "LOCKOUT_ACTIVE", detail: `${active.reason} (lockout ${active.lockoutId})` }
    : null;
}

/** Opened during a session where context/domain trading is disabled
 *  (DEFAULT_SESSION_WINDOWS' tradingEnabled flags — same source T06 already
 *  reuses for its session breakdown). */
export function detectSessionViolation(
  openedAt: UtcTimestamp,
  windows: SessionWindow[],
): Violation | null {
  const session = sessionForTimestamp(openedAt, windows);
  if (sessionEnabled(session, windows)) {
    return null;
  }
  return { type: "SESSION_WINDOW", detail: `opened during ${session} (trading disabled this session)` };
}

/** Trades within this factor of the policy-approved max are not flagged —
 *  evaluateSignalRisk floors its own approved volume to 2 decimals, so a
 *  trade taken at exactly the approved size can land a hair above the raw
 *  (unfloored) max here purely from that rounding, not a real violation. */
const SIZE_TOLERANCE = 1.05;

/**
 * Size exceeds what the risk policy would have approved, computed
 * symbol-generically from tick size/value (lib/market/symbols/registry.ts)
 * — never lib/risk/sizing.ts's XAUUSD-only shortcut. `balance` is the
 * fiche's Décision 2 approximation (current balance, not balance-at-trade-
 * time — no historical account.snapshot table exists yet). Returns null,
 * never a false violation, when there's nothing to judge against (no
 * captured stop, or stop was never set — 0 is MT5's "unset" convention,
 * not a real level).
 */
export function detectSizeViolation(
  volume: number,
  entryPrice: number,
  stopLoss: number,
  balance: number,
  policy: Pick<RiskPolicy, "maxRiskPerTradePercent">,
  metadata: Pick<SymbolMetadata, "tickSize" | "tickValue">,
): Violation | null {
  if (stopLoss <= 0) {
    return null;
  }
  const stopDistance = Math.abs(entryPrice - stopLoss);
  if (stopDistance <= 0 || metadata.tickSize <= 0) {
    return null;
  }
  const riskUsd = (balance * policy.maxRiskPerTradePercent) / 100;
  const riskPerLot = (stopDistance / metadata.tickSize) * metadata.tickValue;
  if (riskPerLot <= 0) {
    return null;
  }
  const maxVolume = riskUsd / riskPerLot;
  if (volume <= maxVolume * SIZE_TOLERANCE) {
    return null;
  }
  return {
    type: "SIZE_POLICY",
    detail: `${volume.toFixed(2)} lot exceeds the ${policy.maxRiskPerTradePercent}% risk budget (~${maxVolume.toFixed(2)} lot max, current balance)`,
  };
}
