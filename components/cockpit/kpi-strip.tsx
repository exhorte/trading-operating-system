"use client";

import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatMoney, formatPercent, formatSignedMoney } from "@/lib/format";
import { Skeleton } from "@/components/ui/skeleton";

interface Kpi {
  label: string;
  value: string;
  tone?: "profit" | "loss" | "warning" | "default";
}

function KpiCell({ kpi }: { kpi: Kpi }) {
  const toneClass =
    kpi.tone === "profit"
      ? "text-profit"
      : kpi.tone === "loss"
        ? "text-loss"
        : kpi.tone === "warning"
          ? "text-warning"
          : "text-foreground";
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2">
      <p className="text-[10px] font-medium uppercase tracking-wider text-muted">{kpi.label}</p>
      <p className={`tnum mt-0.5 text-sm font-semibold ${toneClass}`}>{kpi.value}</p>
    </div>
  );
}

export function KpiStrip() {
  const { account, risk, positions, agents } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (!account || !risk) {
    return (
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">
        {Array.from({ length: 8 }).map((_, index) => (
          <Skeleton key={index} className="h-14" />
        ))}
      </div>
    );
  }

  const connectedAgents = agents.filter((agent) => agent.state === "connected").length;
  const kpis: Kpi[] = [
    { label: "Equity", value: formatMoney(account.equity) },
    {
      label: "Daily P&L",
      value: formatSignedMoney(account.dailyPnl),
      tone: account.dailyPnl >= 0 ? "profit" : "loss",
    },
    {
      label: "Daily drawdown",
      value: formatPercent(account.dailyDrawdownPercent),
      tone: account.dailyDrawdownPercent >= risk.dailyLossLimitPercent * 0.6 ? "warning" : "default",
    },
    {
      label: "Total drawdown",
      value: formatPercent(account.totalDrawdownPercent),
      tone: account.totalDrawdownPercent >= risk.maxDrawdownLimitPercent * 0.6 ? "warning" : "default",
    },
    { label: "Open risk", value: formatPercent(account.openRiskPercent) },
    {
      label: "Risk state",
      value: risk.state.toUpperCase(),
      tone: risk.state === "normal" ? "profit" : risk.state === "warning" ? "warning" : "loss",
    },
    { label: "Active positions", value: String(positions.length) },
    {
      label: "Agents",
      value: `${connectedAgents}/${agents.length} online`,
      tone: connectedAgents === agents.length ? "profit" : "loss",
    },
  ];

  return (
    <div
      className={`grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8 ${untrusted ? "opacity-60" : ""}`}
    >
      {kpis.map((kpi) => (
        <KpiCell key={kpi.label} kpi={kpi} />
      ))}
    </div>
  );
}
