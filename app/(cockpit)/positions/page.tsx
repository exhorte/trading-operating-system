import { EmptyState } from "@/components/ui/empty-state";

export default function PositionsPage() {
  return (
    <EmptyState
      title="Positions & execution workspace not built yet"
      description="Pending commands, broker errors, and reconciliation state require the execution contracts. Open positions are visible on the Command Center."
      hint="Planned: Phase 02 — Domain Model MVP"
    />
  );
}
