import { AgentHealthPanel } from "@/components/cockpit/agent-health-panel";
import { AgentsMetrics } from "@/components/cockpit/agents-metrics";
import { AuditFeed } from "@/components/cockpit/audit-feed";
import { ExecutionReportsFeed } from "@/components/cockpit/execution-reports-feed";
import { PageHeader } from "@/components/shell/page-header";
import { screenAt } from "@/components/shell/nav";
import { SplitLayout } from "@/components/ui/split-layout";

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
 *
 * Composition (ADR 0017): the links on the left, the dark panel of their
 * health on the right, the reports and the audit trail as full-width lists.
 */
export default function AgentsPage() {
  return (
    <div className="flex flex-col gap-10">
      <SplitLayout
        main={
          <>
            <PageHeader screen={screenAt("/agents")} />
            <AgentHealthPanel />
          </>
        }
        aside={<AgentsMetrics />}
      />
      <ExecutionReportsFeed />
      <AuditFeed />
    </div>
  );
}
