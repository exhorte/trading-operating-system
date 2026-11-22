import { ExecutionCommandsFeed } from "@/components/cockpit/execution-commands-feed";
import { StartupScreen } from "@/components/cockpit/startup-panel";
import { SystemCenterScreen } from "@/components/cockpit/system-center-screen";
import { PageHeader } from "@/components/shell/page-header";
import { screenAt } from "@/components/shell/nav";

/**
 * Système — « le système peut-il trader, et sinon qu'est-ce qui bloque ».
 *
 * Since ADR 0043 (2026-11-14) it holds what three screens held: the start-up and its conditions with the automatic gesture (was /demarrage),
 * the MetaTrader terminals and their agents (was the System Center), and the commands the system sent (was /agents). Once the pilot runs, a
 * person comes here only to see why something is red.
 */
export default function SystemPage() {
  return (
    <div className="flex flex-col gap-10">
      <PageHeader screen={screenAt("/system")} />
      <StartupScreen />
      <SystemCenterScreen />
      <ExecutionCommandsFeed />
    </div>
  );
}
