"use client";

import Link from "next/link";
import { Crosshair, Layers, Target, TrendingUp, Wallet } from "lucide-react";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { useComplianceRate } from "@/lib/compliance/use-compliance-rate";
import { VIOLATION_LABELS } from "@/lib/compliance/labels";
import type { ViolationType } from "@/lib/compliance/violations";
import { tightestHeadroom } from "@/lib/cockpit/verdict";
import { formatMoney, formatPercent, formatSignedMoney } from "@/lib/format";
import {
  HighlightBar,
  MetricPanel,
  MetricPanelItem,
  MetricPanelList,
  type MetricTone,
} from "@/components/ui/metric-panel";
import { Skeleton } from "@/components/ui/skeleton";

const VIOLATION_TYPES: ViolationType[] = ["LOCKOUT_ACTIVE", "SESSION_WINDOW", "SIZE_POLICY"];

/**
 * The Command Center's key figures, in the dark panel: equity as the headline,
 * then the four numbers that qualify it — the day's P&L, the room left before
 * a lock (the tightest of the limits, detailed on /risk), the compliance rate
 * (T07, the product's KPI — the single mint chip of the panel) and what is
 * open. The three violation counts of the compliance rate close the panel.
 */
export function CommandCenterMetrics() {
  const { account, risk, positions } = useCockpit();
  const untrusted = useIsDataUntrusted();
  const compliance = useComplianceRate();

  if (!account) {
    return (
      <>
        <Skeleton className="h-[72px] rounded-xl" />
        <Skeleton className="h-[420px] rounded-xl" />
      </>
    );
  }

  const headroom = risk ? tightestHeadroom(risk) : null;
  const headroomTone: MetricTone | undefined = !headroom
    ? undefined
    : headroom.usedRatio > 0.8
      ? "destructive"
      : headroom.usedRatio > 0.5
        ? "warning"
        : undefined;
  const dailyPnlPercent = account.balance > 0 ? (account.dailyPnl / account.balance) * 100 : null;

  const { rate, tradeCount, breachedCount, byType, lookbackDays, failed } = compliance;
  // No trade in the window reads 100 % — a discipline figure that says 100 %
  // because it has nothing to read is worse than an empty one. Nothing
  // measured, nothing shown.
  const measured = rate !== null && tradeCount > 0;
  const percent = measured ? Math.round(rate * 100) : null;
  const complianceTone: MetricTone | undefined = !measured
    ? undefined
    : rate >= 0.9
      ? "success"
      : rate >= 0.7
        ? "warning"
        : "destructive";

  return (
    <>
      <HighlightBar
        icon={Wallet}
        value={formatMoney(account.equity)}
        label="Equity"
        aside={<span className="text-xs text-panel-muted">solde {formatMoney(account.balance)}</span>}
        className={untrusted ? "opacity-60" : undefined}
      />
      <MetricPanel>
        <MetricPanelItem
          label="P&L du jour"
          value={formatSignedMoney(account.dailyPnl)}
          tone={account.dailyPnl >= 0 ? "success" : "destructive"}
          hint={
            dailyPnlPercent === null
              ? "flottant compris, depuis le début de la journée"
              : `${dailyPnlPercent >= 0 ? "+" : ""}${formatPercent(dailyPnlPercent)} · flottant compris, depuis le début de la journée`
          }
          icon={TrendingUp}
          untrusted={untrusted}
        />
        <MetricPanelItem
          label="Marge avant verrou"
          value={headroom ? headroom.remaining : "—"}
          tone={headroomTone}
          hint={
            headroom
              ? `${headroom.label} · ${Math.round(headroom.usedRatio * 100)} % consommé`
              : "pas de moteur de risque"
          }
          icon={Crosshair}
          untrusted={untrusted}
        />
        <MetricPanelItem
          label="Conformité au plan"
          value={percent === null ? "—" : String(percent)}
          unit={percent === null ? undefined : "%"}
          tone={complianceTone}
          solidIcon
          icon={Target}
          hint={
            <>
              {!measured
                ? failed
                  ? "trades clôturés illisibles — le backend répond-il ?"
                  : rate === null
                    ? "lecture des trades clôturés…"
                    : "aucun trade clôturé sur la période — rien à mesurer"
                : `${tradeCount - breachedCount} trade(s) dans le cadre sur ${tradeCount} · ${lookbackDays} derniers jours`}{" "}
              <Link href="/risk" className="text-panel-foreground underline underline-offset-4">
                Détail
              </Link>
            </>
          }
        />
        <MetricPanelItem
          label="Positions ouvertes"
          value={String(positions.length)}
          hint={`risque ouvert ${formatPercent(account.openRiskPercent)}`}
          icon={Layers}
          untrusted={untrusted}
        />
        <MetricPanelList
          items={VIOLATION_TYPES.map((type) => ({ label: VIOLATION_LABELS[type], value: byType[type] }))}
        />
      </MetricPanel>
    </>
  );
}
