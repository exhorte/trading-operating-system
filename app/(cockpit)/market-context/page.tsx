import { EconomicCalendar } from "@/components/cockpit/economic-calendar";
import { MarketContextPanel } from "@/components/cockpit/market-context-panel";

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
 */
export default function MarketContextPage() {
  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-5 lg:grid-cols-2">
        <MarketContextPanel />
        <EconomicCalendar />
      </div>
      <p className="text-xs text-muted-foreground">
        Les niveaux affichés viennent de <code className="text-foreground">lib/analysis</code> —
        source de niveaux, jamais source de signal (ADR 0002). Le graphique annoté
        (liquidité, FVG, OB, BOS/CHOCH) n&apos;est pas construit.
      </p>
    </div>
  );
}
