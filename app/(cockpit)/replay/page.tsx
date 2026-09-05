import { EmptyState } from "@/components/ui/empty-state";

export default function ReplayPage() {
  return (
    <EmptyState
      title="Replay workspace not built yet"
      description="Decision replay (what the framework saw, why risk approved, what the broker returned) requires stored market context and the analytics pipeline."
      hint="Planned: après la Vague 2 — analytics pipeline"
    />
  );
}
