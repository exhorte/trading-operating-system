import { ComplianceCard } from "@/components/cockpit/compliance-card";
import { KpiStrip } from "@/components/cockpit/kpi-strip";
import { PositionsTable } from "@/components/cockpit/positions-table";
import { SessionVerdictBanner } from "@/components/cockpit/session-verdict-banner";

/**
 * Command Center — « où j'en suis, là, maintenant ».
 *
 * One question, three blocks: the verdict, the four numbers that qualify it,
 * and what is actually open. It carried ~104 distinct values across four
 * different time horizons until 2026-09-20 (now / today / this month / market
 * structure); each of the other horizons now has its own screen:
 *
 *   market structure -> /market-context
 *   today's limits   -> /risk
 *   this month       -> /journal
 *   machine health   -> /agents
 *
 * 2026-09-24 redesign, after the reference mock-up: the verdict becomes the
 * hero card, the compliance rate (T07 — the product's KPI) moves here from
 * the top bar and sits beside it, then the four numbers, then the positions.
 * Nothing was added that was not already on this screen or in its header.
 * See context/frontend/information_architecture.md.
 */
export default function CommandCenterPage() {
  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-5 xl:grid-cols-3">
        <SessionVerdictBanner className="xl:col-span-2" />
        <ComplianceCard />
      </div>
      <KpiStrip />
      <PositionsTable />
    </div>
  );
}
