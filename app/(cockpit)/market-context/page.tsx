import { EconomicCalendar } from "@/components/cockpit/economic-calendar";
import { MarketContextPanel } from "@/components/cockpit/market-context-panel";
import { MarketMetrics } from "@/components/cockpit/market-metrics";
import { PageHeader } from "@/components/shell/page-header";
import { screenAt } from "@/components/shell/nav";
import { Callout } from "@/components/ui/callout";
import { SplitLayout } from "@/components/ui/split-layout";

/**
 * Market Context — « pourquoi le marché est dans cet état ».
 *
 * Was an empty placeholder until 2026-09-20. It now owns the live context
 * panel (moved off the Command Center, where it was 13 of the ~104 values
 * competing for the same glance) and the FRED calendar, which existed only as
 * a one-line chip in the top bar while it drives a fail-closed risk gate.
 *
 * Still missing, and deliberately named below rather than implied: the chart
 * with ICT/SMC overlays described in final_interface_spec.md.
 *
 * Composition (ADR 0017): the context on the left, its key figures in the
 * dark panel on the right, the calendar as the full-width list.
 */
export default function MarketContextPage() {
  return (
    <div className="flex flex-col gap-10">
      <SplitLayout
        main={
          <>
            <PageHeader screen={screenAt("/market-context")} />
            <MarketContextPanel />
          </>
        }
        aside={<MarketMetrics />}
      />
      <EconomicCalendar />
      <Callout title="Important">
        Les niveaux affichés viennent de <code className="text-foreground">lib/analysis</code>{" "}
        — source de niveaux, jamais source de signal (ADR 0002). Le graphique annoté (liquidité, FVG, OB, BOS/CHOCH)
        n&apos;est pas construit.
      </Callout>
    </div>
  );
}
