import { EmptyState } from "@/components/ui/empty-state";

export default function ReplayPage() {
  return (
    <EmptyState
      title="Replay workspace not built yet"
      description="Decision replay (what the framework saw, why risk approved, what the broker returned) requires stored market context and the analytics pipeline."
      hint="Planned: Phase 07 — Backtesting And Analytics"
    />
  );
}
