/**
 * Execution command builder — the ONLY way a command comes to exist.
 *
 * A PlaceOrderCommand is derived strictly from an approved RiskDecision plus
 * the signal it ruled on: volume is the risk-approved volume (never the
 * strategy's ask), riskApprovalId links the mandatory approval (domain rule:
 * no command without risk approval), and a rejected/unsized decision yields
 * NO command at all. Pure — imports only lib/domain.
 */

import type { AgentId, UtcTimestamp } from "@/lib/domain/primitives";
import type { RiskDecision } from "@/lib/domain/risk";
import type { StrategySignal } from "@/lib/domain/strategy";
import type { PlaceOrderCommand } from "@/lib/domain/execution";

/** How long an issued command stays executable. */
const COMMAND_TTL_MS = 60_000;

export function buildPlaceOrderCommand(args: {
  signal: StrategySignal;
  decision: RiskDecision;
  agentId: AgentId;
  now: UtcTimestamp;
}): PlaceOrderCommand | null {
  const { signal, decision, agentId, now } = args;

  // Hard gates: only an approved, sized decision for THIS signal creates a command.
  if (!decision.approved || decision.approvedVolume === null || decision.approvedVolume <= 0) {
    return null;
  }
  if (decision.signalId !== signal.signalId) {
    return null;
  }

  return {
    kind: "place_order",
    commandId: `cmd-${signal.signalId}`,
    accountId: signal.accountId,
    agentId,
    riskApprovalId: decision.approvalId,
    expiresAt: new Date(Date.parse(now) + COMMAND_TTL_MS).toISOString(),
    issuedAt: now,
    symbol: signal.symbol,
    side: signal.side,
    orderType: "market",
    volume: decision.approvedVolume,
    limitPrice: null,
    stopLoss: signal.stopLoss,
    takeProfit: signal.takeProfit,
    signalId: signal.signalId,
    strategyId: signal.strategyId,
  };
}
