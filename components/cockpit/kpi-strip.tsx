"use client";

import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { tightestHeadroom } from "@/lib/cockpit/verdict";
import { formatMoney, formatPercent, formatSignedMoney } from "@/lib/format";
import { Skeleton } from "@/components/ui/skeleton";

interface Kpi {
  label: string;
  value: string;
  /** One line of context under the number — the unit, the source, or what
   *  the number is a share of. Replaces the ⓘ tooltip pattern: the cockpit
   *  is read at a glance, and a number nobody can hover is a number nobody
   *  can interpret. */
  detail: string;
  tone?: "profit" | "loss" | "warning" | "default";
}

const TONE_CLASSES: Record<NonNullable<Kpi["tone"]>, string> = {
  profit: "text-profit",
  loss: "text-loss",
  warning: "text-warning",
  default: "text-foreground",
};

function KpiCell({ kpi }: { kpi: Kpi }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2.5">
      <p className="text-[10px] font-medium uppercase tracking-wider text-muted">{kpi.label}</p>
      <p className={`tnum mt-1 text-xl font-semibold ${TONE_CLASSES[kpi.tone ?? "default"]}`}>
        {kpi.value}
      </p>
      <p className="mt-0.5 text-[11px] text-muted">{kpi.detail}</p>
    </div>
  );
}

/**
 * Four numbers, deliberately.
 *
 * It carried eight until 2026-09-20; daily drawdown, total drawdown, open
 * risk and risk state were all *components* of the same question — how much
 * room is left before a lock — shown as four peers with no answer between
 * them. They are now one tile ("Marge avant verrou", the tightest of the
 * three limits) and live in full on /risk. See
 * context/frontend/information_architecture.md.
 */
export function KpiStrip() {
  const { account, risk, positions } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (!account) {
    return (
      <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-[74px]" />
        ))}
      </div>
    );
  }

  const headroom = risk ? tightestHeadroom(risk) : null;
  const dailyPnlPercent = account.balance > 0 ? (account.dailyPnl / account.balance) * 100 : null;

  const kpis: Kpi[] = [
    {
      label: "Equity",
      value: formatMoney(account.equity),
      detail: `solde ${formatMoney(account.balance)}`,
    },
    {
      label: "P&L du jour",
      value: formatSignedMoney(account.dailyPnl),
      detail: dailyPnlPercent === null ? "—" : `${formatPercent(dailyPnlPercent)} du solde`,
      tone: account.dailyPnl >= 0 ? "profit" : "loss",
    },
    {
      label: "Marge avant verrou",
      value: headroom ? headroom.remaining : "—",
      detail: headroom
        ? `${headroom.label} · ${Math.round(headroom.usedRatio * 100)}% consommé`
        : "pas de moteur de risque",
      tone: !headroom
        ? "default"
        : headroom.usedRatio > 0.8
          ? "loss"
          : headroom.usedRatio > 0.5
            ? "warning"
            : "profit",
    },
    {
      label: "Positions ouvertes",
      value: String(positions.length),
      detail: `risque ouvert ${formatPercent(account.openRiskPercent)}`,
    },
  ];

  return (
    <div className={`grid grid-cols-2 gap-2 xl:grid-cols-4 ${untrusted ? "opacity-60" : ""}`}>
      {kpis.map((kpi) => (
        <KpiCell key={kpi.label} kpi={kpi} />
      ))}
    </div>
  );
}
