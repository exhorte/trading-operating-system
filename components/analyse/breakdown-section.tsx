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
 */
export function BreakdownSection({ title, narrative, buckets, footnote }: BreakdownSectionProps) {
  const maxAbs = Math.max(1, ...buckets.map((b) => Math.abs(b.pnl)));

  return (
    <Panel title={title}>
      <p className="mb-3 text-xs leading-relaxed text-muted-foreground">{narrative}</p>

      {buckets.length === 0 ? (
        <p className="text-xs text-muted-foreground">Aucune donnée sur cette dimension.</p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="pb-1 font-medium">Tranche</th>
              <th className="pb-1 text-right font-medium">Trades</th>
              <th className="pb-1 pl-3 font-medium">Résultat</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((bucket) => (
              <tr key={bucket.label} className="border-t border-border">
                <td className="py-1.5 pr-2 text-foreground">{bucket.label}</td>
                <td className="tnum py-1.5 text-right text-muted-foreground">{bucket.trades}</td>
                <td className="py-1.5 pl-3">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 min-w-[3rem] flex-1 overflow-hidden rounded bg-muted">
                      <div
                        className={`h-full rounded ${bucket.pnl >= 0 ? "bg-profit" : "bg-loss"}`}
                        style={{ width: `${(Math.abs(bucket.pnl) / maxAbs) * 100}%` }}
                      />
                    </div>
                    <span
                      className={`tnum w-20 shrink-0 text-right font-medium ${
                        bucket.pnl >= 0 ? "text-profit" : "text-loss"
                      }`}
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

      {footnote && <p className="mt-2 text-xs text-muted-foreground">{footnote}</p>}
    </Panel>
  );
}
