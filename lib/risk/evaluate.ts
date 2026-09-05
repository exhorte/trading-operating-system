/**
 * Risk-state evaluator: run every gate over the current account/positions and
 * derive the posture (normal / warning / locked) + lockout reason.
 *
 * Pure — imports only lib/domain and sibling risk modules. Hard lockouts are
 * account-level breaches (daily loss, drawdown, max trades, consecutive losses)
 * that stop ALL trading; spread/session/news are entry gates that block new
 * entries without locking the account. Everything is v0.1 — a hypothesis.
 */

import type { RiskMode, RiskState } from "@/lib/domain/risk";
import { openRiskPercent } from "./open-risk";
import { WARNING_THRESHOLD } from "./policy";
import {
  consecutiveLossGate,
  dailyLossGate,
  maxDrawdownGate,
  maxTradesGate,
  newsGate,
  openRiskGate,
  sessionGate,
  spreadGate,
} from "./gates";
import type { RiskEvaluationInput } from "./types";

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

export function evaluateRiskState(input: RiskEvaluationInput): RiskState {
  const {
    policy,
    initialBalance,
    dayStartEquity,
    equity,
    balance,
    positions,
    tradesToday,
    consecutiveLosses,
    spreadPoints,
    session,
    sessionTradingEnabled,
    upcomingReleases,
    now,
  } = input;

  const denom = initialBalance > 0 ? initialBalance : 1;
  const dailyLossUsedPercent = round1(Math.max(0, ((dayStartEquity - equity) / denom) * 100));
  const maxDrawdownUsedPercent = round1(Math.max(0, ((initialBalance - equity) / denom) * 100));
  const openRisk = openRiskPercent(positions, balance);

  const daily = dailyLossGate(dailyLossUsedPercent, policy);
  const drawdown = maxDrawdownGate(maxDrawdownUsedPercent, policy);
  const trades = maxTradesGate(tradesToday, policy);
  const consecutive = consecutiveLossGate(consecutiveLosses, policy);
  const gates = [
    daily,
    drawdown,
    openRiskGate(openRisk, policy),
    trades,
    consecutive,
    spreadGate(spreadPoints, policy),
    sessionGate(session, sessionTradingEnabled),
    newsGate(upcomingReleases, now, policy),
  ];

  // Account-level lockouts (not the entry-only gates).
  const hardBreaches = [daily, drawdown, trades, consecutive].filter(
    (g) => g.state === "blocked",
  );
  const locked = hardBreaches.length > 0;
  const warning =
    !locked &&
    (dailyLossUsedPercent >= policy.dailyLossLimitPercent * WARNING_THRESHOLD ||
      maxDrawdownUsedPercent >= policy.maxDrawdownLimitPercent * WARNING_THRESHOLD ||
      openRisk >= policy.maxOpenRiskPercent * WARNING_THRESHOLD);

  const mode: RiskMode = locked ? "locked" : warning ? "warning" : "normal";

  return {
    accountId: policy.accountId,
    mode,
    dailyLossUsedPercent,
    maxDrawdownUsedPercent,
    openRiskPercent: openRisk,
    tradesToday,
    consecutiveLosses,
    lockoutReason: locked ? hardBreaches.map((g) => g.label).join("; ") : null,
    lockoutUntil: null,
    gates,
    evaluatedAt: now,
  };
}
