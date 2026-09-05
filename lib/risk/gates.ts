/**
 * FTMO-style safety gates. Each is a pure function returning a RiskGateResult
 * (open/blocked + human-readable detail for the cockpit and audit trail).
 * A gate whose input is unknown (null) reports "open" with an honest "n/a"
 * detail — never a fabricated pass. Vocabulary source: context/domain/risk_ftmo.md.
 */

import type { TradingSession } from "@/lib/domain/primitives";
import type { RiskGateResult } from "@/lib/domain/risk";
import type { RiskPolicy } from "@/lib/domain/risk";

const SESSION_LABELS: Record<TradingSession, string> = {
  asia: "Asia",
  london: "London",
  new_york_am: "NY AM",
  new_york_pm: "NY PM",
  off_session: "Off-session",
};

function pct(n: number): string {
  return `${Math.round(n * 10) / 10}%`;
}

function result(
  gateId: string,
  label: string,
  blocked: boolean,
  detail: string,
): RiskGateResult {
  return { gateId, label, state: blocked ? "blocked" : "open", detail };
}

export function dailyLossGate(usedPercent: number, policy: RiskPolicy): RiskGateResult {
  const blocked = usedPercent >= policy.dailyLossLimitPercent;
  return result(
    "gate-daily-loss",
    "Daily loss guard",
    blocked,
    `${pct(usedPercent)} used of ${pct(policy.dailyLossLimitPercent)}`,
  );
}

export function maxDrawdownGate(usedPercent: number, policy: RiskPolicy): RiskGateResult {
  const blocked = usedPercent >= policy.maxDrawdownLimitPercent;
  return result(
    "gate-total-dd",
    "Max drawdown guard",
    blocked,
    `${pct(usedPercent)} used of ${pct(policy.maxDrawdownLimitPercent)}`,
  );
}

export function openRiskGate(openRiskPercent: number, policy: RiskPolicy): RiskGateResult {
  const blocked = openRiskPercent > policy.maxOpenRiskPercent;
  return result(
    "gate-open-risk",
    "Open risk guard",
    blocked,
    `${pct(openRiskPercent)} open of ${pct(policy.maxOpenRiskPercent)} max`,
  );
}

export function maxTradesGate(tradesToday: number | null, policy: RiskPolicy): RiskGateResult {
  if (tradesToday === null) {
    return result("gate-max-trades", "Max trades/day", false, "n/a (observe)");
  }
  const blocked = tradesToday >= policy.maxTradesPerDay;
  return result(
    "gate-max-trades",
    "Max trades/day",
    blocked,
    `${tradesToday}/${policy.maxTradesPerDay} today`,
  );
}

export function consecutiveLossGate(
  consecutiveLosses: number | null,
  policy: RiskPolicy,
): RiskGateResult {
  if (consecutiveLosses === null) {
    return result("gate-consec-loss", "Consecutive losses", false, "n/a (observe)");
  }
  const blocked = consecutiveLosses >= policy.maxConsecutiveLosses;
  return result(
    "gate-consec-loss",
    "Consecutive losses",
    blocked,
    `${consecutiveLosses}/${policy.maxConsecutiveLosses}`,
  );
}

export function spreadGate(spreadPoints: number | null, policy: RiskPolicy): RiskGateResult {
  if (spreadPoints === null) {
    return result("gate-spread", "Spread gate", false, "n/a (no tick)");
  }
  const blocked = spreadPoints > policy.maxSpreadPoints;
  return result(
    "gate-spread",
    "Spread gate",
    blocked,
    `${Math.round(spreadPoints)} pts ${blocked ? ">" : "<"} ${policy.maxSpreadPoints} pts limit`,
  );
}

export function sessionGate(
  session: TradingSession,
  tradingEnabled: boolean,
): RiskGateResult {
  return result(
    "gate-session",
    "Session filter",
    !tradingEnabled,
    `${SESSION_LABELS[session]} ${tradingEnabled ? "window open" : "entries disabled"}`,
  );
}

/** MVP stub: no news calendar is wired yet, so the gate never blocks. */
export function newsGate(): RiskGateResult {
  return result("gate-news", "News filter", false, "No news feed connected");
}
