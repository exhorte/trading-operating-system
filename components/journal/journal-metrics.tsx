import { BookOpen, Camera, Coins, FlaskConical, ShieldCheck } from "lucide-react";
import { formatSignedMoney } from "@/lib/format";
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

/**
 * The key figures of the period, in the dark panel (ADR 0017). Discipline
 * first, result last: the journal is where the process is read back (ADR
 * 0001), so « dans le cadre » is the highlighted metric and the realised
 * result is a plain sum of the rows below — no expectancy, no profit factor,
 * no curve (T06 fiche, décision 1).
 *
 * `rows` is null while loading or after a failed read: dashes, never zeros.
 */
export function JournalMetrics({
  rows,
  loading,
  rangeLabel,
}: {
  rows: TradeRow[] | null;
  loading: boolean;
  /** « du 07/07 au 08/10 · XAUUSDm » — which window the figures describe. */
  rangeLabel: string;
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
  const proposed = measured ? rows.filter((row) => row.setupDetail !== null).length : null;
  const captured = measured ? rows.filter((row) => row.trade.hasCapture).length : null;
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
          value={proposed === null ? "—" : String(proposed)}
          unit={proposed === null || total === null ? undefined : `/ ${total}`}
          hint="coïncide avec une proposition d'EA-02 à ±5 min"
          icon={FlaskConical}
        />
        <MetricPanelItem
          label="Avec capture"
          value={captured === null ? "—" : String(captured)}
          unit={captured === null || total === null ? undefined : `/ ${total}`}
          hint="entrée rejouable depuis la ligne du trade"
          icon={Camera}
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
