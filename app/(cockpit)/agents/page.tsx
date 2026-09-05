import { EmptyState } from "@/components/ui/empty-state";

export default function ExecutionAgentsPage() {
  return (
    <EmptyState
      title="Execution Agents workspace not built yet"
      description="Agent sessions, telemetry, command history, and reconciliation views arrive with the MT5 agent specification. Live agent health is on the Command Center."
      hint="Not planned — live agent health stays on the Command Center"
    />
  );
}
