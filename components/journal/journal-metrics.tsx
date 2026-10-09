import { BookOpen, Coins, Crosshair, FlaskConical, ShieldCheck } from "lucide-react";
import { formatSignedMoney } from "@/lib/format";
import { setupShare, type SetupContext } from "@/lib/journal/setup-coverage";
import { HighlightBar, MetricPanel, MetricPanelItem, type MetricTone } from "@/components/ui/metric-panel";
import { Skeleton } from "@/components/ui/skeleton";
import type { TradeRow } from "./trades-table";

/** Neutral when nothing was broken, then warning, then error as the share of clean trades drops. */
function frameTone(clean: number, total: number): MetricTone | undefined {
  if (total === 0) {
    return undefined;
  }
  const ratio = clean / total;
  return ratio === 1 ? "success" : ratio >= 0.7 ? "warning" : "destructive";
}

/** « 2026-09-09T19:00:00.000Z » → « 09/09 ». */
const shortDay = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

/** What stands under the S01 figure: where it comes from, or why there is none. */
function setupHint(setup: SetupContext): string {
  switch (setup.status) {
    case "loading":
      return "propositions de S01 en cours de lecture";
    case "unavailable":
      return "propositions de S01 illisibles";
    case "ready":
      return setup.truncated
        ? `depuis le ${shortDay(setup.since)} seulement : le cœur ne lit pas plus loin`
        : "coïncide avec une proposition d'EA-02 à ±5 min";
  }
}

/**
 * The key figures of the period, in the dark panel (ADR 0017). Discipline
 * first, result last: the journal is where the process is read back (ADR
 * 0001), so « dans le cadre » is the highlighted metric and the realised
 * result is a plain sum of the rows below — no expectancy, no profit factor,
 * no curve (T06 fiche, décision 1).
 *
 * `rows` is null while loading or after a failed read: dashes, never zeros. The same goes for the S01 figure, which rests on a
 * second read (`setup`) that can be loading, refused or shorter than the period.
 */
export function JournalMetrics({
  rows,
  loading,
  rangeLabel,
  setup,
}: {
  rows: TradeRow[] | null;
  loading: boolean;
  /** « du 07/07 au 08/10 · XAUUSDm » — which window the figures describe. */
  rangeLabel: string;
  /** The S01 context the « pris sur une proposition » figure is read from. */
  setup: SetupContext;
}) {
  if (loading) {
    return (
      <>
        <Skeleton className="h-[72px] rounded-xl" />
        <Skeleton className="h-[420px] rounded-xl" />
      </>
    );
  }

  const total = rows?.length ?? null;
  // No trade in the window: « 0 / 0 » and a green « +$0.00 » would read as a result — dashes say there is none.
  const measured = rows !== null && rows.length > 0;
  const clean = measured ? rows.filter((row) => row.violations.length === 0).length : null;
  const share = measured
    ? setupShare(
        rows.map((row) => ({ openedAt: row.trade.openedAt, closedAt: row.trade.closedAt, proposed: row.setupDetail !== null })),
        setup,
      )
    : null;
  // « A row exists in the captures » is not « the stop is known » (the core backfills entry and exit from the deal history of a
  // trade it did not see open): what the trader reads here is whether the R of the trade can be computed, so that is what is counted.
  const withR = measured ? rows.filter((row) => row.r !== null).length : null;
  const net = measured ? rows.reduce((sum, row) => sum + row.trade.realizedPnl, 0) : null;

  return (
    <>
      <HighlightBar
        icon={BookOpen}
        value={total === null ? "—" : String(total)}
        label="trades clôturés"
        aside={<span className="text-xs text-panel-muted">{rangeLabel}</span>}
      />
      <MetricPanel>
        <MetricPanelItem
          label="Dans le cadre"
          value={clean === null ? "—" : String(clean)}
          unit={clean === null || total === null ? undefined : `/ ${total}`}
          tone={clean === null || total === null ? undefined : frameTone(clean, total)}
          hint={total === null ? "journal illisible" : "sans manquement détectable (T07)"}
          icon={ShieldCheck}
          solidIcon
        />
        <MetricPanelItem
          label="Pris sur une proposition S01"
          value={share === null ? "—" : String(share.proposed)}
          unit={share === null ? undefined : `/ ${share.of}`}
          hint={setupHint(setup)}
          icon={FlaskConical}
        />
        <MetricPanelItem
          label="R calculable"
          value={withR === null ? "—" : String(withR)}
          unit={withR === null || total === null ? undefined : `/ ${total}`}
          hint="entrée et stop connus : sans stop posé, pas de R"
          icon={Crosshair}
        />
        <MetricPanelItem
          label="Résultat réalisé"
          value={net === null ? "—" : formatSignedMoney(net)}
          tone={net === null ? undefined : net >= 0 ? "success" : "destructive"}
          hint="somme des lignes affichées — un fait, pas un indicateur"
          icon={Coins}
        />
      </MetricPanel>
    </>
  );
}
