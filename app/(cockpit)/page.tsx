import Link from "next/link";
import { Layers } from "lucide-react";
import { CommandCenterMetrics } from "@/components/cockpit/command-center-metrics";
import { PositionsTable } from "@/components/cockpit/positions-table";
import { SessionVerdictBanner } from "@/components/cockpit/session-verdict-banner";
import { WhyNoTradePanel } from "@/components/cockpit/why-no-trade-panel";
import { PageHeader, SectionHeading } from "@/components/shell/page-header";
import { screenAt } from "@/components/shell/nav";
import { Button } from "@/components/ui/button";
import { SplitLayout } from "@/components/ui/split-layout";

/**
 * Command Center — « où j'en suis, là, maintenant ».
 *
 * One question, three blocks: the verdict (left), the key figures that
 * qualify it (the dark panel, right) and what is actually open (the list
 * below). It carried ~104 distinct values across four different time horizons
 * until 2026-09-20; each of the other horizons now has its own screen:
 *
 *   market structure -> /market-context
 *   today's limits   -> /risk
 *   this month       -> /journal
 *   machine health   -> /agents
 *
 * ADR 0017 (ExponentValue): the compliance rate (T07 — the product's KPI)
 * moved into the dark panel as its single highlighted metric. Nothing was
 * added that was not already on this screen. See
 * context/frontend/information_architecture.md.
 */
export default function CommandCenterPage() {
  return (
    <div className="flex flex-col gap-10">
      <SplitLayout
        main={
          <>
            <PageHeader screen={screenAt("/")} />
            <SessionVerdictBanner />
            <WhyNoTradePanel />
          </>
        }
        aside={<CommandCenterMetrics />}
      />

      <section className="flex flex-col gap-4">
        <SectionHeading
          title="Positions ouvertes"
          subtitle="suivies en direct"
          icon={Layers}
          actions={
            <Button asChild variant="secondary" size="sm">
              <Link href="/positions">Voir tout</Link>
            </Button>
          }
        />
        <PositionsTable />
      </section>
    </div>
  );
}
