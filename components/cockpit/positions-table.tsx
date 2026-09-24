"use client";

import Link from "next/link";
import { ArrowRight, Layers } from "lucide-react";
import { cn } from "cn";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatPrice, formatSignedMoney } from "@/lib/format";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";

const HEADERS = ["Symbole", "Sens", "Volume", "Entrée", "Cours", "SL", "TP", "P&L latent", "R", "Stratégie", ""];

/** What is open right now — the only thing on the Command Center one can act on.
 *  Also heads /positions, where the "view all" link would point to itself. */
export function PositionsTable({ showViewAll = true }: { showViewAll?: boolean }) {
  const { positions, connection } = useCockpit();
  const untrusted = useIsDataUntrusted();

  const viewAll = showViewAll ? (
    <Link
      href="/positions"
      className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
    >
      Voir tout
      <ArrowRight className="size-3.5" />
    </Link>
  ) : undefined;

  if (connection === "connecting") {
    return (
      <Panel title="Positions ouvertes" icon={Layers} actions={viewAll}>
        <Skeleton className="h-28 rounded-xl" />
      </Panel>
    );
  }

  return (
    <Panel
      title="Positions ouvertes"
      description={positions.length > 0 ? `${positions.length} position(s) suivie(s) en direct` : undefined}
      icon={Layers}
      actions={viewAll}
      untrusted={untrusted}
    >
      {positions.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border py-10 text-center text-sm text-muted-foreground">
          Aucune position ouverte.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                {HEADERS.map((header, index) => (
                  <th key={`${header}-${index}`} className="pr-4 pb-3 font-medium">
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {positions.map((position) => (
                <tr
                  key={position.positionId}
                  className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/40"
                >
                  <td className="py-3 pr-4 font-medium">{position.symbol}</td>
                  <td className="py-3 pr-4">
                    <StatusPill tone={position.side === "buy" ? "profit" : "loss"}>
                      {position.side === "buy" ? "Achat" : "Vente"}
                    </StatusPill>
                  </td>
                  <td className="tnum py-3 pr-4">{position.volume.toFixed(2)}</td>
                  <td className="tnum py-3 pr-4">{formatPrice(position.entryPrice)}</td>
                  <td className="tnum py-3 pr-4">{formatPrice(position.currentPrice)}</td>
                  <td className="tnum py-3 pr-4 text-loss/80">{formatPrice(position.stopLoss)}</td>
                  <td className="tnum py-3 pr-4 text-profit/80">{formatPrice(position.takeProfit)}</td>
                  <td
                    className={cn(
                      "tnum py-3 pr-4 font-medium",
                      position.unrealizedPnl >= 0 ? "text-profit" : "text-loss",
                    )}
                  >
                    {formatSignedMoney(position.unrealizedPnl)}
                  </td>
                  <td className={cn("tnum py-3 pr-4", position.rMultiple >= 0 ? "text-profit" : "text-loss")}>
                    {position.rMultiple.toFixed(2)}
                  </td>
                  <td className="py-3 pr-4 text-muted-foreground">{position.strategyId}</td>
                  <td className="py-3 text-right">
                    {/* T05: entry capture is server-recorded the moment the
                        position was observed opening — link, not a button,
                        since there's nothing to trigger here. */}
                    <Link
                      href={`/journal/${position.positionId}`}
                      className="text-xs text-muted-foreground transition-colors hover:text-primary"
                    >
                      Capture →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
