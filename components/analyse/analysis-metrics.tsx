import { Coins, Hash, Percent, ShieldAlert, ShieldCheck } from "lucide-react";
import type { GeneralStats } from "@/lib/account-analysis/breakdowns";
import type { ComplianceSummary } from "@/lib/compliance/summarize";
import { formatPercent, formatSignedMoney } from "@/lib/format";
import { HighlightBar, MetricPanel, MetricPanelItem } from "@/components/ui/metric-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

/**
 * Same bands and same words as the discipline gauge and the top-bar badge
 * (components/cockpit/discipline-gauge.tsx) — one rule, read three times: the
 * pill must never say something the gauge would not.
 */
export function complianceBand(rate: number): { tone: PillTone; label: string } {
  if (rate >= 0.9) {
    return { tone: "profit", label: "Conforme" };
  }
  if (rate >= 0.7) {
    return { tone: "warning", label: "À surveiller" };
  }
  return { tone: "loss", label: "Hors cadre" };
}

/**
 * The key figures of the analysed period, in the dark panel (ADR 0017).
 * Discipline first and result second — the product is the process (ADR 0001),
 * so the headline is the compliance rate and the P&L comes after the count of
 * rules that were broken. `data` is null while the period loads.
 */
export function AnalysisMetrics({
  data,
  loading,
}: {
  data: { general: GeneralStats; compliance: ComplianceSummary } | null;
  loading: boolean;
}) {
  if (loading || data === null) {
    return (
      <>
        <Skeleton className="h-[72px] rounded-xl" />
        <Skeleton className="h-[420px] rounded-xl" />
      </>
    );
  }

  const { general, compliance } = data;
  const rate = compliance.rate ?? 0;
  const band = complianceBand(rate);

  return (
    <>
      <HighlightBar
        icon={ShieldCheck}
        value={`${Math.round(rate * 100)} %`}
        label="conformité sur la période"
        aside={
          <StatusPill tone={band.tone} onPanel pulse={rate < 0.7}>
            {band.label}
          </StatusPill>
        }
      />
      <MetricPanel>
        <MetricPanelItem
          label="Trades en manquement"
          value={String(compliance.breachedCount)}
          unit={`/ ${compliance.tradeCount}`}
          tone={compliance.breachedCount === 0 ? "success" : "destructive"}
          hint="comptés en occurrences, pas en dollars"
          icon={ShieldAlert}
          solidIcon
        />
        <MetricPanelItem
          label="Trades clôturés"
          value={String(general.tradeCount)}
          hint={`${general.wins} gagnant${general.wins > 1 ? "s" : ""} · ${general.losses} perdant${general.losses > 1 ? "s" : ""}`}
          icon={Hash}
        />
        <MetricPanelItem
          label="Résultat net"
          value={formatSignedMoney(general.netPnl)}
          tone={general.netPnl >= 0 ? "success" : "destructive"}
          hint="somme des P&L réalisés"
          icon={Coins}
        />
        <MetricPanelItem
          label="Taux de réussite"
          value={formatPercent(general.winRate * 100)}
          hint="trades clôturés au-dessus de zéro"
          icon={Percent}
        />
      </MetricPanel>
    </>
  );
}
