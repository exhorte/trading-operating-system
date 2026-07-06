import { EmptyState } from "@/components/ui/empty-state";

export default function SignalsPage() {
  return (
    <EmptyState
      title="Signals workspace not built yet"
      description="The full signal lifecycle view (detected, scored, risk review, approved, commanded, reported) needs the domain contracts. The live signal queue is on the Command Center."
      hint="Planned: Phase 02 — Domain Model MVP"
    />
  );
}
