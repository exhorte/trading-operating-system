"use client";

import Link from "next/link";
import { cn } from "cn";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import type { Position } from "@/lib/contracts/snapshots";
import { formatPrice, formatSignedMoney } from "@/lib/format";
import { DataList, MobileCardHeader, MobileFields, type Column } from "@/components/ui/data-list";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";

const pnlClass = (value: number) => (value >= 0 ? "text-success" : "text-destructive");

const SideBadge = ({ side }: { side: Position["side"] }) => (
  <StatusPill tone={side === "buy" ? "profit" : "loss"}>{side === "buy" ? "Achat" : "Vente"}</StatusPill>
);

/** T05: the entry capture is server-recorded the moment the position was observed opening — a link, not a button. */
const CaptureLink = ({ id }: { id: string }) => (
  <Link
    href={`/journal/${id}`}
    className="text-xs text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
  >
    Capture →
  </Link>
);

const COLUMNS: Column<Position>[] = [
  { key: "symbol", header: "Symbole", cell: (p) => <span className="font-medium">{p.symbol}</span> },
  { key: "side", header: "Sens", cell: (p) => <SideBadge side={p.side} /> },
  { key: "volume", header: "Volume", align: "right", cell: (p) => p.volume.toFixed(2) },
  { key: "entry", header: "Entrée", align: "right", cell: (p) => formatPrice(p.entryPrice) },
  { key: "price", header: "Cours", align: "right", cell: (p) => formatPrice(p.currentPrice) },
  {
    key: "sl",
    header: "SL",
    align: "right",
    cell: (p) => <span className="text-muted-foreground">{formatPrice(p.stopLoss)}</span>,
  },
  {
    key: "tp",
    header: "TP",
    align: "right",
    cell: (p) => <span className="text-muted-foreground">{formatPrice(p.takeProfit)}</span>,
  },
  {
    key: "pnl",
    header: "P&L latent",
    align: "right",
    cell: (p) => <span className={cn("font-medium", pnlClass(p.unrealizedPnl))}>{formatSignedMoney(p.unrealizedPnl)}</span>,
  },
  {
    key: "r",
    header: "R",
    align: "right",
    cell: (p) => <span className={pnlClass(p.rMultiple)}>{p.rMultiple.toFixed(2)}</span>,
  },
  { key: "strategy", header: "Stratégie", cell: (p) => <span className="text-muted-foreground">{p.strategyId}</span> },
  { key: "capture", header: "", align: "right", cell: (p) => <CaptureLink id={p.positionId} /> },
];

/**
 * What is open right now — the only thing on the Command Center one can act
 * on. A dark-header table from `md` up, one card per position below. Also
 * heads /positions. The screen puts its own title above (SectionHeading).
 */
export function PositionsTable() {
  const { positions, connection } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (connection === "connecting") {
    return <Skeleton className="h-28 rounded-xl" />;
  }

  if (positions.length === 0) {
    return (
      <p className="rounded-xl border border-dashed py-10 text-center text-sm text-muted-foreground">
        Aucune position ouverte.
      </p>
    );
  }

  return (
    <div className={cn("transition-opacity", untrusted && "opacity-60")}>
      <DataList
        rows={positions}
        columns={COLUMNS}
        rowKey={(p) => p.positionId}
        mobileCard={(p) => (
          <>
            <MobileCardHeader name={p.symbol} subtitle={p.strategyId} badge={<SideBadge side={p.side} />} />
            <MobileFields
              fields={[
                { label: "Volume", value: p.volume.toFixed(2) },
                { label: "Entrée", value: formatPrice(p.entryPrice) },
                { label: "Cours", value: formatPrice(p.currentPrice) },
                { label: "SL", value: formatPrice(p.stopLoss) },
                { label: "TP", value: formatPrice(p.takeProfit) },
                {
                  label: "P&L latent",
                  value: <span className={pnlClass(p.unrealizedPnl)}>{formatSignedMoney(p.unrealizedPnl)}</span>,
                },
              ]}
            />
            <div className="mt-3 flex items-center justify-between text-xs">
              <span className={cn("tabular-nums", pnlClass(p.rMultiple))}>R {p.rMultiple.toFixed(2)}</span>
              <CaptureLink id={p.positionId} />
            </div>
          </>
        )}
      />
    </div>
  );
}
