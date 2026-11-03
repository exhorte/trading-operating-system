import { cn } from "cn";
import { formatSignedMoney } from "@/lib/format";
import { Panel } from "@/components/ui/panel";

export interface DayBucket {
  label: string;
  trades: number;
  pnl: number;
}

/** Monday first — the week of a French-speaking trader. */
const WEEKDAY_HEADERS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"];

/**
 * One month's realised P&L, day by day (T06). Weeks run Monday to Sunday and
 * the grid is padded to full weeks; a day with trades is tinted by the sign
 * of its result, a day without stays blank.
 */
export function MonthCalendar({
  year,
  month,
  dayTotals,
}: {
  year: number;
  /** 0-based, as `Date`. */
  month: number;
  dayTotals: Map<string, DayBucket>;
}) {
  // getUTCDay(): 0 = Sunday. Shifted so that Monday is column 0.
  const leading = (new Date(Date.UTC(year, month, 1)).getUTCDay() + 6) % 7;
  const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();

  const cells: Array<{ day: number; key: string } | null> = [];
  for (let i = 0; i < leading; i++) {
    cells.push(null);
  }
  for (let day = 1; day <= daysInMonth; day++) {
    cells.push({ day, key: `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}` });
  }
  while (cells.length % 7 !== 0) {
    cells.push(null);
  }

  const monthLabel = new Date(Date.UTC(year, month, 1)).toLocaleDateString("fr-FR", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
  const monthTotal = cells.reduce((sum, cell) => sum + (cell ? (dayTotals.get(cell.key)?.pnl ?? 0) : 0), 0);
  const traded = cells.some((cell) => cell && dayTotals.has(cell.key));

  return (
    <Panel
      title={<span className="capitalize">{monthLabel}</span>}
      actions={
        traded ? (
          <span className={cn("text-sm font-medium tabular-nums", monthTotal >= 0 ? "text-success" : "text-destructive")}>
            {formatSignedMoney(monthTotal)}
          </span>
        ) : undefined
      }
    >
      <div className="grid grid-cols-7 gap-1 text-center text-[0.6875rem]">
        {WEEKDAY_HEADERS.map((weekday) => (
          <div key={weekday} className="pb-1 font-medium tracking-wider text-muted-foreground uppercase">
            {weekday}
          </div>
        ))}
        {cells.map((cell, index) => {
          if (!cell) {
            return <div key={`pad-${index}`} />;
          }
          const bucket = dayTotals.get(cell.key);
          return (
            <div
              key={cell.key}
              title={bucket ? `${bucket.trades} trade${bucket.trades > 1 ? "s" : ""}` : undefined}
              className={cn(
                "flex min-h-11 flex-col items-center justify-center gap-0.5 rounded-md border p-1",
                bucket && (bucket.pnl >= 0 ? "border-success/20 bg-success/10" : "border-destructive/20 bg-destructive/10"),
              )}
            >
              {/* On a tinted day the secondary grey falls to 4.4:1 (green tint) — the body colour keeps it readable. */}
              <span className={bucket ? "text-foreground" : "text-muted-foreground"}>{cell.day}</span>
              {bucket && (
                <span
                  className={cn(
                    "text-[0.625rem] leading-none font-medium tabular-nums",
                    bucket.pnl >= 0 ? "text-success" : "text-destructive",
                  )}
                >
                  {formatSignedMoney(bucket.pnl)}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </Panel>
  );
}
