"use client";

import { Crosshair, Layers, TrendingUp, Wallet } from "lucide-react";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { tightestHeadroom } from "@/lib/cockpit/verdict";
import { formatMoney, formatPercent, formatSignedMoney } from "@/lib/format";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { KpiCard, type KpiTone } from "./kpi-card";

/**
 * Four numbers, deliberately.
 *
 * It carried eight until 2026-09-20; daily drawdown, total drawdown, open
 * risk and risk state were all *components* of the same question — how much
 * room is left before a lock — shown as four peers with no answer between
 * them. They are now one tile ("Marge avant verrou", the tightest of the
 * three limits) and live in full on /risk. See
 * context/frontend/information_architecture.md.
 *
 * Restyled 2026-09-24 after the reference mock-up (large light figures,
 * soft pills, thin bars); the numbers and their meaning did not change.
 */
export function KpiStrip() {
  const { account, risk, positions } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (!account) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-[148px] rounded-2xl" />
        ))}
      </div>
    );
  }

  const headroom = risk ? tightestHeadroom(risk) : null;
  const dailyPnlPercent = account.balance > 0 ? (account.dailyPnl / account.balance) * 100 : null;
  const headroomTone: KpiTone = !headroom
    ? "default"
    : headroom.usedRatio > 0.8
      ? "loss"
      : headroom.usedRatio > 0.5
        ? "warning"
        : "profit";

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <KpiCard
        label="Equity"
        value={formatMoney(account.equity)}
        detail={`solde ${formatMoney(account.balance)}`}
        icon={Wallet}
        untrusted={untrusted}
      />
      <KpiCard
        label="P&L du jour"
        value={formatSignedMoney(account.dailyPnl)}
        tone={account.dailyPnl >= 0 ? "profit" : "loss"}
        badge={
          dailyPnlPercent === null ? undefined : (
            <StatusPill tone={account.dailyPnl >= 0 ? "profit" : "loss"}>
              {`${account.dailyPnl >= 0 ? "+" : ""}${formatPercent(dailyPnlPercent)}`}
            </StatusPill>
          )
        }
        detail="flottant compris, depuis le début de la journée"
        icon={TrendingUp}
        untrusted={untrusted}
      />
      <KpiCard
        label="Marge avant verrou"
        value={headroom ? headroom.remaining : "—"}
        tone={headroomTone}
        progress={headroom ? (1 - headroom.usedRatio) * 100 : undefined}
        detail={
          headroom
            ? `${headroom.label} · ${Math.round(headroom.usedRatio * 100)} % consommé`
            : "pas de moteur de risque"
        }
        icon={Crosshair}
        untrusted={untrusted}
      />
      <KpiCard
        label="Positions ouvertes"
        value={String(positions.length)}
        detail={`risque ouvert ${formatPercent(account.openRiskPercent)}`}
        icon={Layers}
        untrusted={untrusted}
      />
    </div>
  );
}
