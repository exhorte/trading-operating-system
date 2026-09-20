"use client";

import { useMemo, useState } from "react";
import { useAccountAnalysis } from "@/lib/account-analysis/use-account-analysis";
import {
  describeDays,
  describeDuration,
  describeGeneral,
  describeOpenHour,
  describeSide,
  describeSize,
  describeSymbol,
  describeTradingDays,
} from "@/lib/account-analysis/narrative";
import { VIOLATION_LABELS } from "@/lib/compliance/labels";
import type { ViolationType } from "@/lib/compliance/violations";
import { useCockpit } from "@/lib/realtime/provider";
import { formatPercent, formatSignedMoney } from "@/lib/format";
import { BreakdownSection } from "@/components/analyse/breakdown-section";
import { StatTile } from "@/components/analyse/stat-tile";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

const inputClass =
  "rounded border border-border bg-surface-elevated px-2 py-1 text-xs text-foreground";

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function defaultFrom(): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - 30);
  return isoDate(d);
}

function money(value: number | null): string {
  return value === null ? "—" : formatSignedMoney(value);
}

/**
 * Analyse de compte — « qu'est-ce que mes données disent de mon process ».
 *
 * Adapted from FTMO's "Analyse de compte" report: one generated sentence per
 * dimension, then the numbers. Three deliberate departures from the model:
 *
 *  1. **Discipline first, P&L second.** FTMO's report is a performance
 *     post-mortem; here the process is the product (ADR 0001), so the
 *     compliance block sits above every P&L breakdown.
 *  2. **No advice.** FTMO closes blocks with "focus only on those trades that
 *     turned out successful" — post-hoc candidate selection, the exact error
 *     that ended the edge research (ADR 0002). The sentences here describe
 *     and stop.
 *  3. **No trade table.** That is `/journal`, and T08's fiche (Décision 1)
 *     was right that a second one would be pointless. This screen only
 *     aggregates; to see rows, go to the journal.
 *
 * It shares T08's data and detectors but not its scope: T08 renders a week to
 * a Markdown file you keep, this reads any range on screen.
 */
export default function AccountAnalysisPage() {
  const { account } = useCockpit();
  const [from, setFrom] = useState(defaultFrom);
  const [to, setTo] = useState(() => isoDate(new Date()));

  const { loading, failed, trades, general, tradingDays, breakdowns, compliance } =
    useAccountAnalysis(from, to);

  const violationEntries = useMemo(
    () =>
      (Object.keys(compliance.byType) as ViolationType[])
        .map((type) => ({ type, count: compliance.byType[type] }))
        .sort((a, b) => b.count - a.count),
    [compliance.byType],
  );

  if (!account) {
    return (
      <EmptyState
        title="Aucun compte connecté"
        description="L'analyse porte sur les trades clôturés d'un compte. Le cockpit doit être relié à la chaîne temps réel pour savoir lequel."
      />
    );
  }

  const rangeCard = (
    <Card title="Période analysée">
      <div className="flex flex-wrap items-center gap-3 text-xs">
        <label className="flex items-center gap-1.5">
          <span className="text-muted">Du</span>
          <input
            type="date"
            value={from}
            max={to}
            onChange={(e) => setFrom(e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="flex items-center gap-1.5">
          <span className="text-muted">Au</span>
          <input
            type="date"
            value={to}
            min={from}
            onChange={(e) => setTo(e.target.value)}
            className={inputClass}
          />
        </label>
        <span className="text-muted">{account.label}</span>
      </div>
    </Card>
  );

  if (failed) {
    return (
      <div className="flex flex-col gap-2">
        {rangeCard}
        <EmptyState
          title="Analyse indisponible"
          description="Les trades clôturés n'ont pas pu être chargés. Le backend répond-il ? docker ps doit montrer tradingos-backend et tradingos-timescaledb."
        />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex flex-col gap-2">
        {rangeCard}
        <Skeleton className="h-40" />
        <Skeleton className="h-64" />
      </div>
    );
  }

  if (trades.length === 0) {
    return (
      <div className="flex flex-col gap-2">
        {rangeCard}
        <EmptyState
          title="Aucun trade clôturé sur cette période"
          description="Élargis la plage de dates. Cet écran n'analyse que des positions déjà fermées — une position ouverte n'a ni durée ni résultat."
        />
      </div>
    );
  }

  const rate = compliance.rate ?? 0;
  const complianceTone: PillTone = rate >= 0.9 ? "profit" : rate >= 0.7 ? "warning" : "loss";

  return (
    <div className="flex flex-col gap-2">
      {rangeCard}

      {/* Le résumé, en une phrase générée — le motif central du modèle FTMO. */}
      <Card title="Ce que la période dit">
        <p className="text-sm leading-relaxed text-foreground">{describeGeneral(general)}</p>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
          <StatTile
            label="Trades"
            value={String(general.tradeCount)}
            detail={`${general.wins} gagnants · ${general.losses} perdants`}
          />
          <StatTile
            label="Résultat net"
            value={formatSignedMoney(general.netPnl)}
            detail="somme des P&L réalisés"
            tone={general.netPnl >= 0 ? "profit" : "loss"}
          />
          <StatTile
            label="Taux de réussite"
            value={formatPercent(general.winRate * 100)}
            detail="trades clôturés au-dessus de zéro"
          />
          <StatTile
            label="Gain moyen"
            value={money(general.avgWin)}
            detail="moyenne des trades gagnants"
            tone={general.avgWin === null ? "default" : "profit"}
          />
          <StatTile
            label="Perte moyenne"
            value={money(general.avgLoss)}
            detail="moyenne des trades perdants"
            tone={general.avgLoss === null ? "default" : "loss"}
          />
          <StatTile
            label="Rapport gain / perte"
            value={general.rewardRiskRatio === null ? "—" : general.rewardRiskRatio.toFixed(2)}
            detail="gain moyen ÷ |perte moyenne|"
          />
        </div>
      </Card>

      {/* ADR 0001 : la discipline passe avant le P&L, y compris dans l'ordre
          de lecture de la page. */}
      <Card
        title="Discipline sur la période"
        actions={
          <StatusPill tone={complianceTone} pulse={rate < 0.7}>
            {Math.round(rate * 100)}% conformité
          </StatusPill>
        }
      >
        <p className="text-xs leading-relaxed text-muted">
          {compliance.breachedCount === 0
            ? `Aucun des ${compliance.tradeCount} trades de la période n'enfreint une règle détectable.`
            : `${compliance.breachedCount} trade(s) sur ${compliance.tradeCount} enfreignent au moins une règle détectable.`}{" "}
          Les manquements sont comptés en occurrences, pas en dollars — une règle enfreinte
          n&apos;a pas de prix.
        </p>
        <ul className="mt-3 flex flex-col gap-1.5">
          {violationEntries.map(({ type, count }) => (
            <li key={type} className="flex items-center justify-between gap-2 text-xs">
              <span className={count > 0 ? "text-foreground" : "text-muted"}>
                {VIOLATION_LABELS[type]}
              </span>
              <span className={`tnum ${count > 0 ? "text-loss" : "text-muted"}`}>{count}</span>
            </li>
          ))}
        </ul>
        {compliance.byType.SIZE_POLICY === 0 && (
          <p className="mt-2 text-[11px] text-muted">
            Le contrôle de taille s&apos;appuie sur le solde courant, faute de solde
            historisé — un zéro ici veut dire « rien trouvé avec cette approximation »,
            pas « vérifié sur le solde du jour ».
          </p>
        )}
      </Card>

      <Card title="Séances">
        <p className="mb-3 text-xs leading-relaxed text-muted">
          {describeTradingDays(tradingDays)}
        </p>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-6">
          <StatTile
            label="Séances"
            value={String(tradingDays.dayCount)}
            detail="jours avec au moins une clôture"
          />
          <StatTile
            label="Trades / séance"
            value={tradingDays.avgTradesPerDay?.toFixed(1) ?? "—"}
            detail="moyenne sur la période"
          />
          <StatTile
            label="Séances positives"
            value={String(tradingDays.positiveDays)}
            detail={`moyenne ${money(tradingDays.avgPositiveDay)}`}
            tone={tradingDays.positiveDays > 0 ? "profit" : "default"}
          />
          <StatTile
            label="Séances négatives"
            value={String(tradingDays.negativeDays)}
            detail={`moyenne ${money(tradingDays.avgNegativeDay)}`}
            tone={tradingDays.negativeDays > 0 ? "loss" : "default"}
          />
          <StatTile
            label="Meilleure séance"
            value={money(tradingDays.bestDay?.pnl ?? null)}
            detail={tradingDays.bestDay?.label ?? "—"}
            tone="profit"
          />
          <StatTile
            label="Pire séance"
            value={money(tradingDays.worstDay?.pnl ?? null)}
            detail={tradingDays.worstDay?.label ?? "—"}
            tone="loss"
          />
        </div>
      </Card>

      <div className="grid gap-2 lg:grid-cols-2">
        <BreakdownSection
          title="Par durée de trade"
          narrative={describeDuration(breakdowns.byDuration)}
          buckets={breakdowns.byDuration}
          footnote="Les trades sans ouverture enregistrée sont exclus : leur durée est inconnue, pas nulle."
        />
        <BreakdownSection
          title="Par taille de position"
          narrative={describeSize(breakdowns.bySize)}
          buckets={breakdowns.bySize}
          footnote="En lots, tels qu'exécutés chez le broker."
        />
        <BreakdownSection
          title="Par heure d'entrée"
          narrative={describeOpenHour(breakdowns.byOpenHour)}
          buckets={breakdowns.byOpenHour}
          footnote="Heures UTC — pas l'heure du terminal MT5 ni l'heure locale."
        />
        <BreakdownSection
          title="Achat / Vente"
          narrative={describeSide(breakdowns.bySide)}
          buckets={breakdowns.bySide}
        />
        <BreakdownSection
          title="Par jour d'ouverture"
          narrative={describeDays(breakdowns.byOpenDay, breakdowns.byCloseDay)}
          buckets={breakdowns.byOpenDay}
        />
        <BreakdownSection
          title="Par jour de fermeture"
          narrative="Les mêmes trades, rangés sur le jour où le résultat a été réalisé — c'est cette lecture que suit une limite de perte journalière."
          buckets={breakdowns.byCloseDay}
        />
        <BreakdownSection
          title="Par instrument"
          narrative={describeSymbol(breakdowns.bySymbol)}
          buckets={breakdowns.bySymbol}
        />
      </div>

      <p className="text-xs text-muted">
        Descriptions d&apos;un échantillon, pas propriétés d&apos;un système. Choisir quoi
        trader d&apos;après la tranche qui a le mieux marché ici, c&apos;est exactement la
        sélection a posteriori qui a mis fin à la recherche d&apos;edge (ADR 0002).
      </p>
    </div>
  );
}
