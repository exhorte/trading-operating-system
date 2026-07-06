import { AgentHealthPanel } from "@/components/cockpit/agent-health-panel";
import { ExecutionReportsFeed } from "@/components/cockpit/execution-reports-feed";
import { KpiStrip } from "@/components/cockpit/kpi-strip";
import { MarketContextPanel } from "@/components/cockpit/market-context-panel";
import { PnlCalendar } from "@/components/cockpit/pnl-calendar";
import { PositionsTable } from "@/components/cockpit/positions-table";
import { RiskStatusPanel } from "@/components/cockpit/risk-status-panel";
import { SignalQueue } from "@/components/cockpit/signal-queue";

export default function CommandCenterPage() {
  return (
    <div className="flex flex-col gap-2">
      <KpiStrip />
      <div className="grid gap-2 lg:grid-cols-3">
        <MarketContextPanel />
        <div className="flex flex-col gap-2">
          <RiskStatusPanel />
          <SignalQueue />
        </div>
        <AgentHealthPanel />
      </div>
      <PositionsTable />
      <div className="grid gap-2 lg:grid-cols-2">
        <PnlCalendar />
        <ExecutionReportsFeed />
      </div>
    </div>
  );
}
