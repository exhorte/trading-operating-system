import { cn } from "cn";
import { formatSignedMoney } from "@/lib/format";
import { Panel } from "@/components/ui/panel";
import type { DayBucket } from "./month-calendar";

/** The journal's own aggregation: label, number of trades, realised result. */
export type Bucket = DayBucket;

/** One breakdown of the period (by symbol, session, weekday, entry hour): a compact three-column table. */
export function BreakdownTable({ title, buckets }: { title: string; buckets: Bucket[] }) {
  return (
    <Panel title={title}>
      {buckets.length === 0 ? (
        <p className="text-sm text-muted-foreground">Aucune donnée sur cette dimension.</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="sr-only">
            <tr>
              <th>Tranche</th>
              <th>Trades</th>
              <th>Résultat</th>
            </tr>
          </thead>
          <tbody>
            {buckets.map((bucket) => (
              <tr key={bucket.label} className="border-b last:border-0">
                <td className="py-2 pr-3">{bucket.label}</td>
                <td className="py-2 pr-3 text-right text-muted-foreground tabular-nums">{bucket.trades}</td>
                <td
                  className={cn(
                    "py-2 text-right font-medium tabular-nums",
                    bucket.pnl >= 0 ? "text-success" : "text-destructive",
                  )}
                >
                  {formatSignedMoney(bucket.pnl)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}
