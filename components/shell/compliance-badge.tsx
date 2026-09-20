"use client";

import { useCockpit } from "@/lib/realtime/provider";
import { useComplianceRate } from "@/lib/compliance/use-compliance-rate";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

/**
 * T07 — the single weekly compliance curve, in the top bar where the P&L
 * would otherwise sit (charter.md, principe 2: the KPI is compliance, not
 * P&L on a noisy sample).
 *
 * The computation itself moved to lib/compliance/use-compliance-rate.ts on
 * 2026-09-20 so /risk's discipline gauge reads the same number from the same
 * fetch. This component is now the badge and nothing else.
 */
export function ComplianceBadge() {
  const { account } = useCockpit();
  const { rate } = useComplianceRate();

  if (!account || rate === null) {
    return <StatusPill tone="muted">Conformité —</StatusPill>;
  }

  const percent = Math.round(rate * 100);
  const tone: PillTone = rate >= 0.9 ? "profit" : rate >= 0.7 ? "warning" : "loss";
  return (
    <StatusPill tone={tone} pulse={rate < 0.7}>
      {percent}% conformité (7j)
    </StatusPill>
  );
}
