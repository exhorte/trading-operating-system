"use client";

import { Gauge, Hash, Repeat, ShieldCheck, TrendingDown } from "lucide-react";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatPercent } from "@/lib/format";
import {
  HighlightBar,
  MetricPanel,
  MetricPanelItem,
  type MetricTone,
} from "@/components/ui/metric-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";

/** Neutral while there is room, warning then error as the limit is consumed. */
function limitTone(ratio: number): MetricTone | undefined {
  return ratio > 0.8 ? "destructive" : ratio > 0.5 ? "warning" : undefined;
}

/**
 * The limits of the day in the dark panel: how much of each is consumed. The
 * process is the product (ADR 0001): the P&L does not appear on this screen
 * at all, only the room that is left.
 */
export function RiskMetrics() {
  const { risk } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (!risk) {
    return (
      <>
        <Skeleton className="h-[72px] rounded-xl" />
        <Skeleton className="h-[420px] rounded-xl" />
      </>
    );
  }

  const stateLabel = risk.state === "normal" ? "Normal" : risk.state === "warning" ? "Attention" : "Verrouillé";
  const stateTone = risk.state === "normal" ? "profit" : risk.state === "warning" ? "warning" : "loss";
  const dailyRatio = Math.min(1, risk.dailyLossUsedPercent / risk.dailyLossLimitPercent);
  const drawdownRatio = Math.min(1, risk.maxDrawdownUsedPercent / risk.maxDrawdownLimitPercent);
  const tradesRatio = risk.tradesToday === null ? null : Math.min(1, risk.tradesToday / risk.maxTradesPerDay);

  return (
    <>
      <HighlightBar
        icon={ShieldCheck}
        value={stateLabel}
        label="État du risque"
        aside={
          <StatusPill tone={stateTone} onPanel>
            {risk.state}
          </StatusPill>
        }
        className={untrusted ? "opacity-60" : undefined}
      />
      <MetricPanel>
        <MetricPanelItem
          label="Perte du jour"
          value={formatPercent(risk.dailyLossUsedPercent)}
          unit={`/ ${formatPercent(risk.dailyLossLimitPercent)}`}
          tone={limitTone(dailyRatio)}
          progress={dailyRatio * 100}
          hint="limite journalière"
          icon={TrendingDown}
          untrusted={untrusted}
        />
        <MetricPanelItem
          label="Drawdown maximal"
          value={formatPercent(risk.maxDrawdownUsedPercent)}
          unit={`/ ${formatPercent(risk.maxDrawdownLimitPercent)}`}
          tone={limitTone(drawdownRatio)}
          progress={drawdownRatio * 100}
          hint="limite totale du compte"
          icon={Gauge}
          untrusted={untrusted}
        />
        <MetricPanelItem
          label="Trades du jour"
          value={risk.tradesToday === null ? "n/a" : String(risk.tradesToday)}
          unit={risk.tradesToday === null ? undefined : `/ ${risk.maxTradesPerDay}`}
          tone={tradesRatio === null ? undefined : limitTone(tradesRatio)}
          progress={tradesRatio === null ? undefined : tradesRatio * 100}
          hint={risk.tradesToday === null ? "pas d'historique lisible" : "depuis le début de la journée de trading"}
          icon={Hash}
          untrusted={untrusted}
        />
        <MetricPanelItem
          label="Pertes consécutives"
          value={risk.consecutiveLosses === null ? "n/a" : String(risk.consecutiveLosses)}
          hint="la série ne se remet pas à zéro à minuit"
          icon={Repeat}
          solidIcon
          untrusted={untrusted}
        />
      </MetricPanel>
    </>
  );
}
