"use client";

import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatSignedMoney } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

function cellClasses(pnl: number, trades: number): string {
  if (trades === 0) {
    return "bg-surface-elevated text-muted";
  }
  if (pnl > 0) {
    return pnl > 300 ? "bg-profit/30 text-profit" : "bg-profit/15 text-profit";
  }
  if (pnl < 0) {
    return pnl < -300 ? "bg-loss/30 text-loss" : "bg-loss/15 text-loss";
  }
  return "bg-surface-elevated text-muted";
}

export function PnlCalendar() {
  const { pnlCalendar } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (pnlCalendar.length === 0) {
    return (
      <Card title="P&L calendar">
        <Skeleton className="h-28" />
      </Card>
    );
  }

  const total = pnlCalendar.reduce((sum, day) => sum + day.pnl, 0);

  return (
    <Card
      title="P&L calendar (trading days)"
      untrusted={untrusted}
      actions={
        <span className={`tnum text-xs font-semibold ${total >= 0 ? "text-profit" : "text-loss"}`}>
          {formatSignedMoney(total)}
        </span>
      }
    >
      <div className="grid grid-cols-5 gap-1 sm:grid-cols-10">
        {pnlCalendar.map((day) => (
          <div
            key={day.date}
            title={`${day.date}: ${formatSignedMoney(day.pnl)} (${day.trades} trades)`}
            className={`flex h-10 flex-col items-center justify-center rounded text-center ${cellClasses(day.pnl, day.trades)}`}
          >
            <span className="text-[9px] opacity-70">{day.date.slice(8)}</span>
            <span className="tnum text-[10px] font-medium">
              {day.trades === 0 ? "—" : Math.round(day.pnl)}
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}
