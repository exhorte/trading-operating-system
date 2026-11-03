/**
 * « Pourquoi pas de trade ? » (ADR 0028) — how the core's answer is put on screen. The core orders the reasons and words them; this only
 * labels their source, groups them by whether they block a real order, and formats an opportunity. No rule lives here.
 */

import type { Opportunity, Reason, WhyNoTrade } from "@/lib/api/generated";

export const SOURCE_LABEL: Record<Reason["source"], string> = {
  mode: "Mode",
  guardian: "Gardien",
  risk: "Risque",
  readiness: "Préparation",
  strategy: "Stratégie",
};

/** The tone of the headline: nothing blocks (profit), something waits for a human (warning), a real order cannot leave (muted). */
export function headlineTone(why: WhyNoTrade): "profit" | "warning" | "muted" {
  if (!why.realOrdersPossible) {
    return "muted";
  }
  return why.reasons.some((reason) => reason.source === "mode") ? "warning" : "profit";
}

export interface ReasonGroups {
  blocking: Reason[];
  informing: Reason[];
}

/** Blocking reasons first, in the order the core gave them (the order of reading); the others after. */
export function groupReasons(reasons: readonly Reason[]): ReasonGroups {
  return {
    blocking: reasons.filter((reason) => reason.blocking),
    informing: reasons.filter((reason) => !reason.blocking),
  };
}

export function describeOpportunity(opportunity: Opportunity): string {
  const side = opportunity.side === "buy" ? "Achat" : "Vente";
  const levels = [
    opportunity.entryPrice === null ? null : `entrée ${opportunity.entryPrice}`,
    opportunity.stopLoss === null ? null : `SL ${opportunity.stopLoss}`,
    opportunity.takeProfit === null ? null : `TP ${opportunity.takeProfit}`,
    opportunity.riskRewardRatio === null ? null : `R:R ${opportunity.riskRewardRatio.toFixed(1)}`,
  ].filter((part): part is string => part !== null);
  return `${opportunity.strategyId} · ${side} ${opportunity.symbol}${levels.length > 0 ? ` — ${levels.join(" · ")}` : ""}`;
}
