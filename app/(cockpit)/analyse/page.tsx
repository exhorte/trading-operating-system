"use client";

import { useMemo, useState } from "react";
import { CalendarClock, ChartColumn, ChartColumnBig, ShieldCheck } from "lucide-react";
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
import { formatSignedMoney } from "@/lib/format";
import { AnalysisMetrics } from "@/components/analyse/analysis-metrics";
import { BreakdownSection } from "@/components/analyse/breakdown-section";
import { StatTile } from "@/components/analyse/stat-tile";
import { PageHeader, SectionHeading } from "@/components/shell/page-header";
import { screenAt } from "@/components/shell/nav";
import { Callout } from "@/components/ui/callout";
import { EmptyState } from "@/components/ui/empty-state";
import { FilterBar, FilterField } from "@/components/ui/filter-bar";
import { filterFieldClass } from "@/components/ui/input";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { SplitLayout } from "@/components/ui/split-layout";

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
 *
 * Composition (ADR 0017, « résultats / détail »): title and period on top, the
 * sentence and the discipline block beside the dark panel of the period (which
 * comes first on mobile), then the sessions, the seven breakdowns and the
 * « Important » note.
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
      <div className="flex flex-col gap-10">
        <PageHeader screen={screenAt("/analyse")} />
        <EmptyState
          icon={ChartColumn}
          title="Aucun compte connecté"
          description="L'analyse porte sur les trades clôturés d'un compte. Le cockpit doit être relié à la chaîne temps réel pour savoir lequel."
        />
      </div>
    );
  }

  const header = (
    <div className="flex flex-col gap-6">
      <PageHeader screen={screenAt("/analyse")} />
      <FilterBar label="Période analysée">
        <FilterField label="Du">
          <input
            type="date"
            value={from}
            max={to}
            onChange={(e) => setFrom(e.target.value)}
            className={filterFieldClass}
          />
        </FilterField>
        <FilterField label="Au">
          <input
            type="date"
            value={to}
            min={from}
            onChange={(e) => setTo(e.target.value)}
            className={filterFieldClass}
          />
        </FilterField>
        <p className="ml-auto self-end pb-2 text-sm text-muted-foreground">{account.label}</p>
      </FilterBar>
    </div>
  );

  if (failed) {
    return (
      <div className="flex flex-col gap-10">
        {header}
        <Callout title="Analyse indisponible" variant="warning">
          Les trades clôturés n&apos;ont pas pu être chargés. Le backend répond-il ? <code>docker ps</code> doit
          montrer <code>tradingos-backend</code> et <code>tradingos-timescaledb</code>.
        </Callout>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex flex-col gap-10">
        {header}
        <SplitLayout
          main={
            <>
              <Skeleton className="h-40 rounded-xl" />
              <Skeleton className="h-64 rounded-xl" />
            </>
          }
          aside={<AnalysisMetrics data={null} loading />}
        />
      </div>
    );
  }

  if (trades.length === 0) {
    return (
      <div className="flex flex-col gap-10">
        {header}
        <EmptyState
          icon={ChartColumn}
          title="Aucun trade clôturé sur cette période"
          description="Élargis la plage de dates. Cet écran n'analyse que des positions déjà fermées — une position ouverte n'a ni durée ni résultat."
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-10">
      {header}

      <SplitLayout
        stickyAside
        asideFirstOnMobile
        main={
          <>
            {/* Le résumé, en une phrase générée — le motif central du modèle FTMO. */}
            <Panel title="Ce que la période dit">
              <p className="text-sm leading-relaxed text-foreground">{describeGeneral(general)}</p>
              <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
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
            </Panel>

            {/* ADR 0001 : la discipline passe avant le P&L, y compris dans l'ordre
                de lecture de la page. */}
            <Panel title="Discipline sur la période" icon={ShieldCheck}>
              <p className="text-sm leading-relaxed text-muted-foreground">
                {compliance.breachedCount === 0
                  ? `Aucun des ${compliance.tradeCount} trades de la période n'enfreint une règle détectable.`
                  : `${compliance.breachedCount} trade(s) sur ${compliance.tradeCount} enfreignent au moins une règle détectable.`}{" "}
                Les manquements sont comptés en occurrences, pas en dollars — une règle enfreinte
                n&apos;a pas de prix.
              </p>
              <ul className="mt-4 flex flex-col text-sm">
                {violationEntries.map(({ type, count }) => (
                  <li key={type} className="flex items-center justify-between gap-3 border-t py-2.5">
                    <span className={count > 0 ? "text-foreground" : "text-muted-foreground"}>
                      {VIOLATION_LABELS[type]}
                    </span>
                    <span className={`font-medium tabular-nums ${count > 0 ? "text-destructive" : "text-muted-foreground"}`}>
                      {count}
                    </span>
                  </li>
                ))}
              </ul>
              {compliance.byType.SIZE_POLICY === 0 && (
                <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                  Le contrôle de taille s&apos;appuie sur le solde courant, faute de solde
                  historisé — un zéro ici veut dire « rien trouvé avec cette approximation »,
                  pas « vérifié sur le solde du jour ».
                </p>
              )}
            </Panel>
          </>
        }
        aside={<AnalysisMetrics data={{ general, compliance }} loading={false} />}
      />

      <section className="flex flex-col gap-4">
        <SectionHeading title="Séances" subtitle="la période, jour de clôture par jour de clôture" icon={CalendarClock} />
        <Panel>
          <p className="mb-4 text-sm leading-relaxed text-muted-foreground">{describeTradingDays(tradingDays)}</p>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
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
        </Panel>
      </section>

      <section className="flex flex-col gap-4">
        <SectionHeading title="Répartitions" subtitle="la même période, rangée de sept façons" icon={ChartColumnBig} />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
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
      </section>

      <Callout title="Important">
        Descriptions d&apos;un échantillon, pas propriétés d&apos;un système. Choisir quoi trader d&apos;après la
        tranche qui a le mieux marché ici, c&apos;est exactement la sélection a posteriori qui a mis fin à la
        recherche d&apos;edge (ADR 0002).
      </Callout>
    </div>
  );
}
