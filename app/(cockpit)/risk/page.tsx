import { DisciplineGauge } from "@/components/cockpit/discipline-gauge";
import { LockoutHistory } from "@/components/cockpit/lockout-history";
import { RiskGatesPanel } from "@/components/cockpit/risk-gates-panel";
import { RiskMetrics } from "@/components/cockpit/risk-metrics";
import { PageHeader } from "@/components/shell/page-header";
import { screenAt } from "@/components/shell/nav";
import { Callout } from "@/components/ui/callout";
import { SplitLayout } from "@/components/ui/split-layout";

/**
 * Risque & Discipline — « où en est ma discipline, et combien il me reste
 * avant le verrou ».
 *
 * Was an empty placeholder until 2026-09-20. The discipline score comes first
 * and the limits second, on purpose: the product is the process (ADR 0001),
 * so the compliance rate is the headline and the P&L does not appear on this
 * screen at all.
 *
 * Composition (ADR 0017): the score and the gates on the left, the dark panel
 * of consumed limits on the right, the lockout history as the full-width
 * list, and the « Important » note below.
 */
export default function RiskPage() {
  return (
    <div className="flex flex-col gap-10">
      <SplitLayout
        main={
          <>
            <PageHeader screen={screenAt("/risk")} />
            <DisciplineGauge />
            <RiskGatesPanel />
          </>
        }
        aside={<RiskMetrics />}
        stickyAside
      />
      <LockoutHistory />
      <Callout title="Important">
        Le score de conformité porte sur les trades clôturés passés par ce système. Un ordre saisi directement dans MT5 y
        entre a posteriori, une fois la position fermée — il n&apos;a été contraint par aucune de ces limites au moment
        de son ouverture.
      </Callout>
    </div>
  );
}
