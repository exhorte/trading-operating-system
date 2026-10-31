import { cn } from "cn";
import type { Bucket } from "@/lib/account-analysis/breakdowns";
import { formatSignedMoney } from "@/lib/format";
import { Panel } from "@/components/ui/panel";

interface BreakdownSectionProps {
  title: string;
  /** The generated sentence that says what the table says. */
  narrative: string;
  buckets: Bucket[];
  /** Extra line under the table — a unit, a timezone, a caveat. */
  footnote?: string;
}

/**
 * One analysis dimension: the sentence, then the numbers.
 *
 * FTMO's report pairs a prose card with a table *and* a separate bar chart
 * for every dimension — three surfaces per idea, which reads well on a
 * printed report and badly in a cockpit. Here the bar is folded into the
 * table row: the same proportional comparison, a third of the height.
 *
 * Bar width is relative to the largest absolute P&L in the block, so bars
 * compare within a dimension and never across dimensions — there is no
 * shared scale between "par durée" and "par instrument" and pretending
 * otherwise would invite a false reading.
 *
 * The bars are monochrome (ADR 0017: near-black for a gain, grey for a loss —
 * the chart tokens); the sign is carried by the figure beside them, in the
 * semantic colours, and by its « + » / « - ».
 */
export function BreakdownSection({ title, narrative, buckets, footnote }: BreakdownSectionProps) {
  const maxAbs = Math.max(1, ...buckets.map((b) => Math.abs(b.pnl)));

  return (
    <Panel title={title}>
      <p className="mb-4 text-sm leading-relaxed text-muted-foreground">{narrative}</p>

      {buckets.length === 0 ? (
        <p className="text-sm text-muted-foreground">Aucune donnée sur cette dimension.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="pb-2 font-medium">Tranche</th>
              <th className="pb-2 text-right font-medium">Trades</th>
              <th className="pb-2 pl-4 font-medium">Résultat</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((bucket) => (
              <tr key={bucket.label} className="border-t">
                <td className="py-2.5 pr-2 text-foreground">{bucket.label}</td>
                <td className="py-2.5 text-right text-muted-foreground tabular-nums">{bucket.trades}</td>
                <td className="py-2.5 pl-4">
                  <div className="flex items-center gap-3">
                    <div className="h-1.5 min-w-12 flex-1 overflow-hidden rounded-full bg-muted" aria-hidden="true">
                      <div
                        className={cn("h-full rounded-full", bucket.pnl >= 0 ? "bg-chart-1" : "bg-chart-2")}
                        style={{ width: `${(Math.abs(bucket.pnl) / maxAbs) * 100}%` }}
                      />
                    </div>
                    <span
                      className={cn(
                        "w-20 shrink-0 text-right font-medium tabular-nums",
                        bucket.pnl >= 0 ? "text-success" : "text-destructive",
                      )}
                    >
                      {formatSignedMoney(bucket.pnl)}
                    </span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {footnote && <p className="mt-3 text-xs text-muted-foreground">{footnote}</p>}
    </Panel>
  );
}
