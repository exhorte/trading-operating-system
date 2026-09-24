import { AgentHealthPanel } from "@/components/cockpit/agent-health-panel";
import { AuditFeed } from "@/components/cockpit/audit-feed";
import { ExecutionReportsFeed } from "@/components/cockpit/execution-reports-feed";

/**
 * Agents & Audit — « qu'a fait le système, et est-il en vie ».
 *
 * Was an empty placeholder until 2026-09-20. Receives the two machine panels
 * that were competing with trading state on the Command Center (MT5 link
 * health, execution reports) and adds the envelope audit trail, which the
 * backend had served since the persistence slice with no screen to show it.
 *
 * The distinction the agent panel makes matters here more than anywhere: the
 * observer's hello and the EA-05 execution agent's TCP state are two
 * different links, and reading the first as the second is the bug that let
 * the cockpit imply an order could reach MT5 (corrected 2026-09-18).
 */
export default function AgentsPage() {
  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-5 lg:grid-cols-2">
        <AgentHealthPanel />
        <ExecutionReportsFeed />
      </div>
      <AuditFeed />
    </div>
  );
}
