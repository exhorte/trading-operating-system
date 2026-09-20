/**
 * Cockpit derivations over the risk read model.
 *
 * Pure. Imports `lib/contracts/snapshots` only — one layer above the read
 * model, one layer below the components. `lib/risk/` deliberately stays out
 * of reach here: that package is the portable engine over `lib/domain` and
 * must not learn about dashboard shapes.
 *
 * Exists because the armed / not-armed rule was written twice — once on
 * `/preflight` (T09) and once implicitly in the KPI strip's "Risk state"
 * tile. Two copies of a verdict is one copy too many when the verdict is
 * what the trader reads before opening a position.
 */

import type { RiskGate, RiskStatus } from "@/lib/contracts/snapshots";

export interface SessionVerdict {
  /** True only when nothing blocks and the account is not locked. */
  armed: boolean;
  /** Gates that are not open, in the order the engine reported them. */
  blocking: RiskGate[];
  /** Reason text of the active lockout, or null when clear. */
  lockoutReason: string | null;
}

/**
 * The single armed / not-armed rule. `state === "locked"` is checked on top
 * of the gates because a lockout can be held by the ledger (T02a/T02c) while
 * every individual gate still reads open.
 */
export function sessionVerdict(risk: RiskStatus): SessionVerdict {
  const blocking = risk.gates.filter((gate) => gate.state !== "open");
  return {
    armed: blocking.length === 0 && risk.state !== "locked",
    blocking,
    lockoutReason: risk.lockoutReason,
  };
}

export interface Headroom {
  /** Which limit is closest to binding, in the trader's words. */
  label: string;
  /** What is left before that limit, in that limit's own unit. */
  remaining: string;
  /** 0..1 — share of that limit's budget already consumed. */
  usedRatio: number;
}

/** One candidate limit, normalised so limits in different units compare. */
interface Constraint {
  label: string;
  used: number;
  limit: number;
  format: (remaining: number) => string;
}

function formatPoints(remaining: number): string {
  return `${remaining.toFixed(1)} pts`;
}

function formatTrades(remaining: number): string {
  return `${Math.max(0, Math.round(remaining))} trade${Math.round(remaining) === 1 ? "" : "s"}`;
}

/**
 * The limit the trader is closest to breaching, expressed as what is left
 * before it binds.
 *
 * Three limits in two different units (percentage points of equity, and a
 * count of trades) are compared on consumed *share* of their own budget, then
 * the winner is rendered back in its natural unit — a headroom of "1.2 pts"
 * and one of "1 trade" are not comparable numbers, but "80% of the budget
 * spent" and "83% spent" are.
 *
 * `tradesToday` is null on data sources with no trade history (observe
 * prototype); that constraint is then left out rather than counted as zero,
 * which would read as a full budget the system cannot actually vouch for.
 */
export function tightestHeadroom(risk: RiskStatus): Headroom | null {
  const candidates: Constraint[] = [
    {
      label: "perte du jour",
      used: risk.dailyLossUsedPercent,
      limit: risk.dailyLossLimitPercent,
      format: formatPoints,
    },
    {
      label: "drawdown total",
      used: risk.maxDrawdownUsedPercent,
      limit: risk.maxDrawdownLimitPercent,
      format: formatPoints,
    },
  ];

  if (risk.tradesToday !== null) {
    candidates.push({
      label: "trades du jour",
      used: risk.tradesToday,
      limit: risk.maxTradesPerDay,
      format: formatTrades,
    });
  }

  const usable = candidates.filter((c) => c.limit > 0);
  if (usable.length === 0) {
    return null;
  }

  const tightest = usable.reduce((worst, c) =>
    c.used / c.limit > worst.used / worst.limit ? c : worst,
  );

  const usedRatio = Math.min(1, Math.max(0, tightest.used / tightest.limit));
  return {
    label: tightest.label,
    remaining: tightest.format(Math.max(0, tightest.limit - tightest.used)),
    usedRatio,
  };
}
