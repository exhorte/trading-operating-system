/**
 * Per-signal risk decision: size a trade to the risk-per-trade budget and
 * refuse it if the account is locked or any guard blocks entry. This is the
 * "Signal → Risk Review" step from context/domain/risk_ftmo.md.
 *
 * Built and tested here as the reusable core; NOT wired into the signal flow
 * yet (Phase 06 scope). Pure — imports only lib/domain and siblings.
 */

import type { AccountId, SignalId, UtcTimestamp } from "@/lib/domain/primitives";
import type { RiskDecision, RiskPolicy, RiskState } from "@/lib/domain/risk";

export interface SignalRiskInput {
  signalId: SignalId;
  accountId: AccountId;
  entryPrice: number;
  stopLoss: number;
  balance: number;
  state: RiskState;
  policy: RiskPolicy;
  now: UtcTimestamp;
}

export function evaluateSignalRisk(input: SignalRiskInput): RiskDecision {
  const { signalId, accountId, entryPrice, stopLoss, balance, state, policy, now } = input;

  const blockedGate = state.gates.find((g) => g.state === "blocked");
  const stopDistance = Math.abs(entryPrice - stopLoss);

  let approved = true;
  let approvedVolume: number | null = null;
  let reason: string;

  if (state.mode === "locked") {
    approved = false;
    reason = `Rejected: account locked (${state.lockoutReason ?? "risk lockout"})`;
  } else if (blockedGate) {
    approved = false;
    reason = `Rejected: ${blockedGate.label} — ${blockedGate.detail}`;
  } else if (stopDistance <= 0) {
    approved = false;
    reason = "Rejected: no valid stop-loss distance";
  } else {
    const riskUsd = (balance * policy.maxRiskPerTradePercent) / 100;
    // XAUUSD factor: 1.00 price move on 1.0 lot ≈ 100 USD.
    const rawVolume = riskUsd / (stopDistance * 100);
    approvedVolume = Math.max(0.01, Math.floor(rawVolume * 100) / 100);
    reason = `Approved: ${approvedVolume} lot at ${policy.maxRiskPerTradePercent}% risk`;
  }

  return {
    approvalId: `risk-${signalId}`,
    signalId,
    accountId,
    approved,
    approvedVolume,
    gates: state.gates,
    reason,
    decidedAt: now,
  };
}
