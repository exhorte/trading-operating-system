"use client";

import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatPrice, formatSignedMoney } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

const HEADERS = ["Symbol", "Side", "Volume", "Entry", "Current", "SL", "TP", "uP&L", "R", "Strategy"];

export function PositionsTable() {
  const { positions, connection } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (connection === "connecting") {
    return (
      <Card title="Open positions">
        <Skeleton className="h-28" />
      </Card>
    );
  }

  return (
    <Card title="Open positions" untrusted={untrusted}>
      {positions.length === 0 ? (
        <p className="py-6 text-center text-xs text-muted">No open positions.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-xs">
            <thead>
              <tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted">
                {HEADERS.map((header) => (
                  <th key={header} className="pb-1.5 pr-3 font-medium">
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map((position) => (
                <tr key={position.positionId} className="border-b border-border/50 last:border-0">
                  <td className="py-1.5 pr-3 font-medium">{position.symbol}</td>
                  <td
                    className={`py-1.5 pr-3 font-medium ${
                      position.side === "buy" ? "text-profit" : "text-loss"
                    }`}
                  >
                    {position.side.toUpperCase()}
                  </td>
                  <td className="tnum py-1.5 pr-3">{position.volume.toFixed(2)}</td>
                  <td className="tnum py-1.5 pr-3">{formatPrice(position.entryPrice)}</td>
                  <td className="tnum py-1.5 pr-3">{formatPrice(position.currentPrice)}</td>
                  <td className="tnum py-1.5 pr-3 text-loss/80">{formatPrice(position.stopLoss)}</td>
                  <td className="tnum py-1.5 pr-3 text-profit/80">
                    {formatPrice(position.takeProfit)}
                  </td>
                  <td
                    className={`tnum py-1.5 pr-3 font-medium ${
                      position.unrealizedPnl >= 0 ? "text-profit" : "text-loss"
                    }`}
                  >
                    {formatSignedMoney(position.unrealizedPnl)}
                  </td>
                  <td
                    className={`tnum py-1.5 pr-3 ${
                      position.rMultiple >= 0 ? "text-profit" : "text-loss"
                    }`}
                  >
                    {position.rMultiple.toFixed(2)}
                  </td>
                  <td className="py-1.5 text-muted">{position.strategyId}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
