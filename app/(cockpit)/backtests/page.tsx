import { EmptyState } from "@/components/ui/empty-state";

export default function BacktestsPage() {
  return (
    <EmptyState
      title="Backtests workspace not built yet"
      description="Historical data import, scenario replay, and strategy comparison arrive with the backtesting pipeline."
      hint="Planned: Phase 07 — Backtesting And Analytics"
    />
  );
}
