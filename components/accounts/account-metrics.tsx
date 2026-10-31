"use client";

import { Landmark, ShieldCheck, TrendingDown, Wallet } from "lucide-react";
import { useCockpit } from "@/lib/realtime/provider";
import { PROVIDER_NAMES, type AccountProfile } from "@/lib/accounts/profile";
import { formatMoney, formatSignedMoney } from "@/lib/format";
import { HighlightBar, MetricPanel, MetricPanelItem, type MetricTone } from "@/components/ui/metric-panel";
import { StatusPill } from "@/components/ui/status-pill";

/**
 * The active account and what its rules make of it, in the dark panel:
 * the equity as the headline, then the reference capital, the loss budget of
 * the day (and how much of it is used), the floor and the margin left above
 * it. Without a connected account nothing is guessed: dashes and the reason.
 */
export function AccountMetrics({ profile }: { profile: AccountProfile | null }) {
  const { account, risk, registered } = useCockpit();

  const reference = profile?.referenceBalance ?? null;
  const daily = profile?.dailyLossAmount ?? null;
  const floor = profile?.floor ?? null;
  const marginAboveFloor = account && floor !== null ? Math.min(account.balance, account.equity) - floor : null;
  const usedRatio = risk ? Math.min(1, risk.dailyLossUsedPercent / risk.dailyLossLimitPercent) : null;
  const usedTone: MetricTone | undefined =
    usedRatio === null ? undefined : usedRatio > 0.8 ? "destructive" : usedRatio > 0.5 ? "warning" : undefined;

  return (
    <>
      <HighlightBar
        icon={Wallet}
        value={account ? formatMoney(account.equity, account.currency) : "Aucun compte"}
        label={account ? account.label : registered ? `${registered.name} · non rattaché` : "aucun compte actif"}
        aside={
          <StatusPill tone={account ? "profit" : "muted"} onPanel>
            {account ? "Connecté" : "Non connecté"}
          </StatusPill>
        }
      />
      <MetricPanel>
        <MetricPanelItem
          label="Profil du compte"
          value={registered ? PROVIDER_NAMES[registered.provider] : "—"}
          hint={profile ? profile.label : registered ? "règles en cours de lecture…" : "rien tant qu'aucun compte n'est actif"}
          icon={Landmark}
          solidIcon
        />
        <MetricPanelItem
          label="Capital de référence"
          value={reference === null ? (profile ? "Non fixé" : "—") : formatMoney(reference)}
          tone={profile && reference === null ? "warning" : undefined}
          hint={profile ? profile.referenceSource : undefined}
          icon={Wallet}
        />
        <MetricPanelItem
          label="Perte journalière max"
          value={daily === null ? "—" : formatSignedMoney(-daily)}
          tone={usedTone}
          progress={usedRatio === null ? undefined : usedRatio * 100}
          hint={
            profile
              ? `${profile.dailyLossLimitPercent} % de la référence${risk ? ` · ${risk.dailyLossUsedPercent.toFixed(1)} % utilisés` : ""}`
              : undefined
          }
          icon={TrendingDown}
        />
        <MetricPanelItem
          label="Marge avant le plancher"
          value={
            marginAboveFloor === null || !account ? "—" : formatMoney(Math.max(0, marginAboveFloor), account.currency)
          }
          tone={marginAboveFloor !== null && marginAboveFloor <= 0 ? "destructive" : undefined}
          hint={
            floor !== null && profile
              ? `plancher ${formatMoney(floor)} (perte max ${profile.maxDrawdownLimitPercent} %)`
              : "aucun plancher fixe tant que la référence n'est pas fixée"
          }
          icon={ShieldCheck}
        />
      </MetricPanel>
    </>
  );
}
