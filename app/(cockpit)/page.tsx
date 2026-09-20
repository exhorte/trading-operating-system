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
 * Nothing was deleted in that move. See
 * context/frontend/information_architecture.md.
 */
export default function CommandCenterPage() {
  return (
    <div className="flex flex-col gap-2">
      <SessionVerdictBanner />
      <KpiStrip />
      <PositionsTable />
    </div>
  );
}
