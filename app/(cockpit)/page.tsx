import { Layers } from "lucide-react";
import { CloseAllButton } from "@/components/cockpit/close-all-button";
import { CommandCenterMetrics } from "@/components/cockpit/command-center-metrics";
import { PositionsTable } from "@/components/cockpit/positions-table";
import { SystemControls } from "@/components/cockpit/system-controls";
import { WhyNoTradePanel } from "@/components/cockpit/why-no-trade-panel";
import { PageHeader, SectionHeading } from "@/components/shell/page-header";
import { screenAt } from "@/components/shell/nav";
import { SplitLayout } from "@/components/ui/split-layout";

/**
 * Command Center — « où en est le système, là, maintenant ».
 *
 * The mode and the pilot with the two gestures (start, close everything), why no trade was taken, the figures that qualify it (dark panel),
 * and what is open. ADR 0043 (2026-11-14) removed the session verdict (it repeated the readiness) and the link to /positions (deleted: this
 * table is the same one).
 */
export default function CommandCenterPage() {
  return (
    <div className="flex flex-col gap-10">
      <SplitLayout
        main={
          <>
            <PageHeader screen={screenAt("/")} />
            <SystemControls />
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
          actions={<CloseAllButton size="sm" />}
        />
        <PositionsTable />
      </section>
    </div>
  );
}
