import { EmptyState } from "@/components/ui/empty-state";

export default function MarketContextPage() {
  return (
    <EmptyState
      title="Market Context explorer not built yet"
      description="The full bias, structure, liquidity, and PD-array explorer has no roadmap tool yet. A live summary panel is available on the Command Center."
      hint="Engine ready in lib/analysis — explorer UI not planned"
    />
  );
}
