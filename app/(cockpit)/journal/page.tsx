"use client";

import { useEffect, useMemo, useState } from "react";
import { BookOpen, CalendarDays, ChartNoAxesColumn } from "lucide-react";
import { useCockpit } from "@/lib/realtime/provider";
import { backendHttpBase } from "@/lib/realtime/backend-url";
import { sessionForTimestamp } from "@/lib/analysis/sessions";
import { DEFAULT_SESSION_WINDOWS } from "@/lib/analysis/config";
import { reconcile, type ReconciliationTrade } from "@/lib/setup/reconciliation";
import { evaluateTrade, type ComplianceTradeInput } from "@/lib/compliance/evaluate";
import type { LockoutWindow, Violation } from "@/lib/compliance/violations";
import { defaultRiskPolicy } from "@/lib/risk/policy";
import { toCanonicalSymbol } from "@/lib/market/symbols/registry";
import type { JournalTrade } from "@/lib/journal/types";
import type { Side } from "@/lib/domain/primitives";
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

/** Shape of one row from GET /api/setup-proposals (SetupProposalRepository.GetRecentAsync). */
interface SetupProposal {
  symbol: string;
  eventAt: string;
  status: "proposed" | "blocked";
  side: Side | null;
  sweptLevelKind: string | null;
  costRatio: number | null;
  riskRewardRatio: number | null;
}

/** Same tolerance and rationale as the setups screen's own constant
 *  (not exported from there — re-stated here, kept in sync deliberately,
 *  not coincidentally): "un trade pris trois minutes après une proposition
 *  sur le même niveau est le même trade" (EA-02 prompt). */
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

/**
 * R multiple — same formula as the live one in mt5-translate.ts::toPosition
 * (move / risk, direction-adjusted), reimplemented rather than imported: that
 * one takes a live currentPrice, this one a fixed exitPrice, and it returns
 * null (not 0) when there's no denominator — entryPrice/stopLoss only exist
 * via a T05 capture (T06 fiche, Décision 3), so "no capture" and "no stop
 * set" must read as unknown, not as a flat breakeven.
 */
function computeRMultiple(trade: JournalTrade): number | null {
  if (trade.entryPrice === null || trade.stopLoss === null || trade.stopLoss <= 0) {
    return null;
  }
  const direction = trade.side === "buy" ? 1 : -1;
  const move = (trade.exitPrice - trade.entryPrice) * direction;
  const risk = Math.abs(trade.entryPrice - trade.stopLoss);
  return risk > 0 ? Math.round((move / risk) * 100) / 100 : null;
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
function describeProposal(proposal: SetupProposal): string {
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
function bucketBy(trades: JournalTrade[], keyOf: (t: JournalTrade) => string | null): Bucket[] {
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

/**
 * T06 — browsable, filterable trade journal. Zero manual entry: every row
 * comes from closed_trades/position_opens/trade_captures via
 * GET /api/journal/trades (JournalRepository). No new table — see the
 * fiche's Décision 2. Per-trade realized P&L shown as a fact (same as the
 * live uP&L already on positions-table.tsx); no aggregate performance
 * metric (expectancy/profit factor/equity curve) — Décision 1.
 *
 * Composition (ADR 0017): title, filters and the zero-manual-entry note on
 * the left, the dark panel of the period on the right; then the trades, the
 * calendars and the breakdowns at full width. Only the presentation changed:
 * the fetch below is still this page's own (see lib/journal/use-journal-window.ts
 * for why it was never merged with the shared hook).
 */
export default function TradesJournalPage() {
  const { account } = useCockpit();
  const accountId = account?.accountId ?? null;

  const [from, setFrom] = useState(defaultFrom());
  const [to, setTo] = useState(isoDate(new Date()));
  const [symbol, setSymbol] = useState<string>("all");
  const [trades, setTrades] = useState<JournalTrade[] | null>(null);
  const [proposals, setProposals] = useState<SetupProposal[] | null>(null);
  const [lockouts, setLockouts] = useState<LockoutWindow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!accountId) {
      return;
    }
    let cancelled = false;

    async function load() {
      try {
        const base = backendHttpBase();
        const [tradesRes, proposalsRes, lockoutsRes] = await Promise.all([
          fetch(
            `${base}/api/journal/trades?accountId=${encodeURIComponent(accountId!)}` +
              `&from=${from}&to=${to}`,
          ),
          // EA-02 context, best-effort enrichment (fiche Décision — coïncidence,
          // jamais le pourquoi) — its own fetch failing must not break the journal.
          fetch(`${base}/api/setup-proposals?since=${encodeURIComponent(new Date(from).toISOString())}`),
          // T07 — lockout windows up to `to`, for detectLockoutViolation.
          // Best-effort too: a failed fetch degrades to "no violations
          // detected", not to a broken journal.
          fetch(
            `${base}/api/risk/lockouts?accountId=${encodeURIComponent(accountId!)}` +
              `&to=${encodeURIComponent(new Date(to).toISOString())}`,
          ),
        ]);
        if (!tradesRes.ok) {
          throw new Error("journal fetch failed");
        }
        const body = (await tradesRes.json()) as JournalTrade[];
        const proposalBody = proposalsRes.ok ? ((await proposalsRes.json()) as SetupProposal[]) : [];
        const lockoutBody = lockoutsRes.ok ? ((await lockoutsRes.json()) as LockoutWindow[]) : [];
        if (!cancelled) {
          setTrades(body);
          setProposals(proposalBody);
          setLockouts(lockoutBody);
          setError(null);
        }
      } catch {
        if (!cancelled) {
          setError("Impossible de charger le journal des trades.");
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [accountId, from, to]);

  const symbols = useMemo(
    () => Array.from(new Set((trades ?? []).map((t) => t.symbol))).sort(),
    [trades],
  );

  const filtered = useMemo(
    () => (trades ?? []).filter((t) => symbol === "all" || t.symbol === symbol),
    [trades, symbol],
  );

  /** brokerPositionId -> the proposal it coincided with, when EA-02 detected
   *  one within tolerance. Approximation of context, never the user's own
   *  "why" — T04 (the pre-trade ticket that captured that) was retired. */
  const proposalByTrade = useMemo(() => {
    const map = new Map<string, SetupProposal>();
    if (!proposals) {
      return map;
    }
    const reconcilable: ReconciliationTrade[] = filtered
      .filter((t): t is JournalTrade & { openedAt: string } => t.openedAt !== null)
      .map((t) => ({ brokerPositionId: t.brokerPositionId, symbol: t.symbol, side: t.side as Side, openedAt: t.openedAt }));
    const eligible = proposals.filter(
      (p): p is SetupProposal & { side: Side } => p.status === "proposed" && p.side !== null,
    );
    const rows = reconcile(
      eligible.map((p) => ({ symbol: p.symbol, side: p.side, detectedAt: p.eventAt })),
      reconcilable,
      PROPOSAL_TOLERANCE_MINUTES,
    );
    for (const row of rows) {
      if (row.class !== "PROPOSE_ET_PRIS" || !row.brokerPositionId || !row.proposalDetectedAt) {
        continue;
      }
      const proposal = eligible.find((p) => p.symbol === row.symbol && p.eventAt === row.proposalDetectedAt);
      if (proposal) {
        map.set(row.brokerPositionId, proposal);
      }
    }
    return map;
  }, [filtered, proposals]);

  /** brokerPositionId -> violations (T07). Lockout/session are always
   *  judged when openedAt is known; size only when a balance is available
   *  (fiche Décision 2: current balance, an approximation of balance at
   *  trade time — no historical account.snapshot table exists yet). */
  const violationsByTrade = useMemo(() => {
    const map = new Map<string, Violation[]>();
    if (!accountId) {
      return map;
    }
    const policy = defaultRiskPolicy(accountId);
    const balance = account?.balance ?? null;
    for (const t of filtered) {
      const input: ComplianceTradeInput = {
        brokerPositionId: t.brokerPositionId,
        symbol: toCanonicalSymbol(t.symbol),
        openedAt: t.openedAt,
        volume: t.volume,
        entryPrice: t.entryPrice,
        stopLoss: t.stopLoss,
      };
      map.set(t.brokerPositionId, evaluateTrade(input, lockouts, DEFAULT_SESSION_WINDOWS, balance, policy));
    }
    return map;
  }, [filtered, lockouts, accountId, account?.balance]);

  /** The rows as the screen draws them: everything the table and the dark
   *  panel read, computed once. */
  const rows = useMemo<TradeRow[]>(
    () =>
      filtered.map((trade) => {
        const proposal = proposalByTrade.get(trade.brokerPositionId);
        return {
          trade,
          r: computeRMultiple(trade),
          duration: formatDuration(trade.openedAt, trade.closedAt),
          setupDetail: proposal ? describeProposal(proposal) : null,
          violations: violationsByTrade.get(trade.brokerPositionId) ?? [],
        };
      }),
    [filtered, proposalByTrade, violationsByTrade],
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
  const bySession = useMemo(
    () =>
      bucketBy(filtered, (t) =>
        t.openedAt ? sessionForTimestamp(t.openedAt, DEFAULT_SESSION_WINDOWS) : null,
      ),
    [filtered],
  );
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
          aside={<JournalMetrics rows={null} loading rangeLabel="" />}
        />
        <Skeleton className="h-72 rounded-xl" />
      </div>
    );
  }

  const loading = !trades && !error;
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
              Chaque ligne vient des trades clôturés, des ouvertures et des captures enregistrés par le système : rien
              n&apos;est saisi à la main. Le résultat d&apos;un trade est un fait ; aucun indicateur de performance
              agrégé (espérance, profit factor, courbe de capital) n&apos;est calculé ici (fiche T06, décision 1).
            </Callout>
          </>
        }
        aside={<JournalMetrics rows={error ? null : loading ? null : rows} loading={loading} rangeLabel={rangeLabel} />}
        stickyAside
      />

      {error ? (
        <Callout title="Journal illisible" variant="warning">
          {error}{" "}
          Le backend répond-il ? Aucun trade n&apos;est affiché plutôt qu&apos;un journal vide qui laisserait croire
          qu&apos;il n&apos;y en a pas eu.
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
