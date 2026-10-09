"use client";

import { useMemo, useState } from "react";
import { BookOpen, CalendarDays, ChartNoAxesColumn } from "lucide-react";
import type { JournalTradeView, StrategyEvaluation } from "@/lib/api/generated";
import { useApi } from "@/lib/api/use-api";
import { useNow } from "@/lib/cockpit/use-now";
import { useCockpit } from "@/lib/realtime/provider";
import { setupCoverage, type SetupContext } from "@/lib/journal/setup-coverage";
import { useJournalWindow, windowBounds } from "@/lib/journal/use-journal-window";
import { BreakdownTable, type Bucket } from "@/components/journal/breakdown-table";
import { JournalMetrics } from "@/components/journal/journal-metrics";
import { MonthCalendar } from "@/components/journal/month-calendar";
import { TradesTable, type TradeRow } from "@/components/journal/trades-table";
import { PageHeader, SectionHeading } from "@/components/shell/page-header";
import { screenAt } from "@/components/shell/nav";
import { Callout } from "@/components/ui/callout";
import { EmptyState } from "@/components/ui/empty-state";
import { FilterBar, FilterField } from "@/components/ui/filter-bar";
import { filterFieldClass } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { SplitLayout } from "@/components/ui/split-layout";

/** Same tolerance and rationale as the setups screen's own constant: « un trade pris trois minutes après une proposition
 *  sur le même niveau est le même trade » (EA-02 prompt). The core does the matching; this is the window it is asked for. */
const PROPOSAL_TOLERANCE_MINUTES = 5;

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function defaultFrom(): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - 90);
  return isoDate(d);
}

/** « 2026-10-08 » → « 08/10 » — the period label of the dark panel. */
function shortDate(isoDay: string): string {
  return `${isoDay.slice(8, 10)}/${isoDay.slice(5, 7)}`;
}

function formatDuration(openedAt: string | null, closedAt: string): string {
  if (!openedAt) {
    return "—";
  }
  const ms = new Date(closedAt).getTime() - new Date(openedAt).getTime();
  if (ms < 0) {
    return "—";
  }
  const totalSeconds = Math.round(ms / 1000);
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (h > 0) {
    return `${h}h${m}m`;
  }
  if (m > 0) {
    return `${m}m${s}s`;
  }
  return `${s}s`;
}

/** What the EA-02 proposal that coincided with a trade said — the tooltip of its « S01 » pill. */
function describeProposal(proposal: StrategyEvaluation): string {
  const detail = [
    proposal.sweptLevelKind,
    proposal.costRatio !== null ? `coût ${proposal.costRatio.toFixed(2)}` : null,
    proposal.riskRewardRatio !== null ? `R:R ${proposal.riskRewardRatio.toFixed(2)}` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  return detail || "Proposition d'EA-02 coïncidente";
}

/** Aggregates by a key derived per-trade; buckets with no key (e.g. no
 *  openedAt) are dropped rather than pooled under a fake "unknown" bucket
 *  the pnl total would otherwise silently absorb. */
function bucketBy(trades: JournalTradeView[], keyOf: (t: JournalTradeView) => string | null): Bucket[] {
  const byLabel = new Map<string, Bucket>();
  for (const t of trades) {
    const label = keyOf(t);
    if (label === null) {
      continue;
    }
    const existing = byLabel.get(label);
    if (existing) {
      existing.trades += 1;
      existing.pnl += t.realizedPnl;
    } else {
      byLabel.set(label, { label, trades: 1, pnl: t.realizedPnl });
    }
  }
  return Array.from(byLabel.values());
}

/** Index = `getUTCDay()` (0 = Sunday). Shown Monday first, like the calendars. */
const WEEKDAY_LABELS = ["Dim", "Lun", "Mar", "Mer", "Jeu", "Ven", "Sam"];
const mondayFirst = (label: string) => (WEEKDAY_LABELS.indexOf(label) + 6) % 7;

const TRADE_EVENTS = ["position.closed"] as const;

/**
 * T06 — browsable, filterable trade journal. Zero manual entry: every row
 * comes from the closed trades, the opens and the levels the core recorded
 * (GET /api/journal/trades). Per-trade realized P&L shown as a fact (same as
 * the live uP&L already on positions-table.tsx); no aggregate performance
 * metric (expectancy/profit factor/equity curve) — Décision 1.
 *
 * The R multiple and the rules each trade broke are the core's verdicts,
 * judged against the lockouts and the rules *as they were* — this page
 * recomputes none of it. What it still does is lay the rows out: filter,
 * group, draw.
 *
 * Composition (ADR 0017): title, filters and the zero-manual-entry note on
 * the left, the dark panel of the period on the right; then the trades, the
 * calendars and the breakdowns at full width.
 */
export default function TradesJournalPage() {
  const { activeAccountId: accountId } = useCockpit();

  const [from, setFrom] = useState(defaultFrom());
  const [to, setTo] = useState(isoDate(new Date()));
  const [symbol, setSymbol] = useState<string>("all");

  const { trades, failed, error } = useJournalWindow(accountId, from, to, { trades: true });

  // EA-02 context, best-effort enrichment (fiche Décision — coïncidence, jamais le pourquoi): its own read failing must not
  // break the journal, and must not read as « none of these trades was taken on a proposal ». The core answers for the last
  // month only (a longer look-back is refused), so a longer period gets the end of it and the panel says so.
  const now = useNow(60_000);
  const coverage = setupCoverage(windowBounds(from, to).start, now);
  const proposals = useApi(
    "strategy_proposals",
    accountId ? { query: { since: coverage.since, status: "proposed", limit: 5000 } } : null,
    { refreshOn: ["strategy.evaluation_completed"] },
  );
  const agreement = useApi(
    "strategy_agreement",
    accountId ? { query: { accountId, since: coverage.since, toleranceMinutes: PROPOSAL_TOLERANCE_MINUTES } } : null,
    { refreshOn: ["strategy.evaluation_completed", ...TRADE_EVENTS] },
  );
  const setup: SetupContext =
    proposals.data && agreement.data
      ? { status: "ready", ...coverage }
      : (proposals.error && !proposals.data) || (agreement.error && !agreement.data)
        ? { status: "unavailable" }
        : { status: "loading" };

  const symbols = useMemo(() => Array.from(new Set((trades ?? []).map((t) => t.symbol))).sort(), [trades]);

  const filtered = useMemo(
    () => (trades ?? []).filter((t) => symbol === "all" || t.symbol === symbol),
    [trades, symbol],
  );

  /** brokerPositionId -> the proposal it coincided with, when the core matched one within tolerance. Approximation of
   *  context, never the user's own "why" — T04 (the pre-trade ticket that captured that) was retired. */
  const proposalByTrade = useMemo(() => {
    const map = new Map<string, StrategyEvaluation>();
    if (!agreement.data || !proposals.data) {
      return map;
    }
    for (const row of agreement.data) {
      if (row.agreement !== "PROPOSE_ET_PRIS" || !row.brokerPositionId || !row.proposalDetectedAt) {
        continue;
      }
      const proposal = proposals.data.find((p) => p.symbol === row.symbol && p.eventAt === row.proposalDetectedAt);
      if (proposal) {
        map.set(row.brokerPositionId, proposal);
      }
    }
    return map;
  }, [agreement.data, proposals.data]);

  /** The rows as the screen draws them: everything the table and the dark panel read, computed once. */
  const rows = useMemo<TradeRow[]>(
    () =>
      filtered.map((trade) => {
        const proposal = proposalByTrade.get(trade.brokerPositionId);
        return {
          trade,
          r: trade.rMultiple,
          duration: formatDuration(trade.openedAt, trade.closedAt),
          setupDetail: proposal ? describeProposal(proposal) : null,
          violations: trade.violations,
        };
      }),
    [filtered, proposalByTrade],
  );

  const dayTotals = useMemo(() => {
    const map = new Map<string, Bucket>();
    for (const t of filtered) {
      const key = t.closedAt.slice(0, 10);
      const existing = map.get(key);
      if (existing) {
        existing.trades += 1;
        existing.pnl += t.realizedPnl;
      } else {
        map.set(key, { label: key, trades: 1, pnl: t.realizedPnl });
      }
    }
    return map;
  }, [filtered]);

  const months = useMemo(() => {
    const seen = new Map<string, { year: number; month: number }>();
    for (const t of filtered) {
      const d = new Date(t.closedAt);
      const key = `${d.getUTCFullYear()}-${d.getUTCMonth()}`;
      if (!seen.has(key)) {
        seen.set(key, { year: d.getUTCFullYear(), month: d.getUTCMonth() });
      }
    }
    return Array.from(seen.values()).sort((a, b) => a.year - b.year || a.month - b.month);
  }, [filtered]);

  const bySymbol = useMemo(() => bucketBy(filtered, (t) => t.symbol), [filtered]);
  const bySession = useMemo(() => bucketBy(filtered, (t) => t.session), [filtered]);
  const byWeekday = useMemo(
    () =>
      bucketBy(filtered, (t) => (t.openedAt ? WEEKDAY_LABELS[new Date(t.openedAt).getUTCDay()] : null)).sort(
        (a, b) => mondayFirst(a.label) - mondayFirst(b.label),
      ),
    [filtered],
  );
  const byHour = useMemo(
    () =>
      bucketBy(filtered, (t) =>
        t.openedAt ? String(new Date(t.openedAt).getUTCHours()).padStart(2, "0") + "h UTC" : null,
      ).sort((a, b) => a.label.localeCompare(b.label)),
    [filtered],
  );

  if (!accountId) {
    return (
      <div className="flex flex-col gap-10">
        <SplitLayout
          main={
            <>
              <PageHeader screen={screenAt("/journal")} />
              <Skeleton className="h-24 rounded-xl" />
            </>
          }
          aside={<JournalMetrics rows={null} loading rangeLabel="" setup={{ status: "loading" }} />}
        />
        <Skeleton className="h-72 rounded-xl" />
      </div>
    );
  }

  const loading = !trades && !failed;
  const rangeLabel = `du ${shortDate(from)} au ${shortDate(to)}${symbol === "all" ? "" : ` · ${symbol}`}`;

  return (
    <div className="flex flex-col gap-10">
      <SplitLayout
        main={
          <>
            <PageHeader screen={screenAt("/journal")} />
            <FilterBar>
              <FilterField label="Du">
                <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={filterFieldClass} />
              </FilterField>
              <FilterField label="Au">
                <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className={filterFieldClass} />
              </FilterField>
              <FilterField label="Symbole">
                <select value={symbol} onChange={(e) => setSymbol(e.target.value)} className={filterFieldClass}>
                  <option value="all">Tous</option>
                  {symbols.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </FilterField>
            </FilterBar>
            <Callout title="Zéro saisie manuelle">
              Chaque ligne vient des trades clôturés, des ouvertures et des niveaux (entrée, stop, objectif) enregistrés par le système : rien
              n&apos;est saisi à la main. Le résultat d&apos;un trade est un fait ; aucun indicateur de performance
              agrégé (espérance, profit factor, courbe de capital) n&apos;est calculé ici (fiche T06, décision 1).
            </Callout>
          </>
        }
        aside={
          <JournalMetrics rows={failed ? null : loading ? null : rows} loading={loading} rangeLabel={rangeLabel} setup={setup} />
        }
        stickyAside
      />

      {failed ? (
        <Callout title="Journal illisible" variant="warning">
          {error?.message ?? "Impossible de charger le journal des trades."} Aucun trade n&apos;est affiché plutôt
          qu&apos;un journal vide qui laisserait croire qu&apos;il n&apos;y en a pas eu.
        </Callout>
      ) : loading ? (
        <Skeleton className="h-72 rounded-xl" />
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={BookOpen}
          title="Aucun trade clôturé sur cette période"
          description="Élargis la plage de dates, ou retire le filtre de symbole."
          hint="Zéro saisie manuelle : les lignes apparaissent toutes seules à la clôture des trades."
        />
      ) : (
        <>
          <section className="flex flex-col gap-4">
            <SectionHeading
              title="Trades"
              subtitle={`${filtered.length} clôturé${filtered.length > 1 ? "s" : ""} sur la période`}
              icon={BookOpen}
            />
            <TradesTable rows={rows} />
          </section>

          <section className="flex flex-col gap-4">
            <SectionHeading title="Calendrier" subtitle="résultat réalisé jour par jour" icon={CalendarDays} />
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
              {months.map(({ year, month }) => (
                <MonthCalendar key={`${year}-${month}`} year={year} month={month} dayTotals={dayTotals} />
              ))}
            </div>
          </section>

          <section className="flex flex-col gap-4">
            <SectionHeading title="Répartition" subtitle="la même période, rangée de quatre façons" icon={ChartNoAxesColumn} />
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
              <BreakdownTable title="Par symbole" buckets={bySymbol} />
              <BreakdownTable title="Par session" buckets={bySession} />
              <BreakdownTable title="Par jour de la semaine" buckets={byWeekday} />
              <BreakdownTable title="Par heure d'entrée" buckets={byHour} />
            </div>
          </section>
        </>
      )}
    </div>
  );
}
