import Link from "next/link";
import { cn } from "cn";
import { VIOLATION_LABELS } from "@/lib/compliance/labels";
import type { Violation } from "@/lib/compliance/violations";
import { formatQuote, formatSignedMoney } from "@/lib/format";
import type { JournalTrade } from "@/lib/journal/types";
import { DataList, MobileCardHeader, MobileFields, type Column } from "@/components/ui/data-list";
import { StatusPill } from "@/components/ui/status-pill";

/** One line of the journal, already computed by the page: this file only draws it. */
export interface TradeRow {
  trade: JournalTrade;
  /** R multiple; null = unknown (no capture, or no stop was set) — never a flat zero. */
  r: number | null;
  duration: string;
  /** What the EA-02 proposal that coincided with this trade said; null when none did. */
  setupDetail: string | null;
  violations: Violation[];
}

const pnlClass = (value: number) => (value >= 0 ? "text-success" : "text-destructive");

function formatClosedAt(iso: string): string {
  return new Date(iso).toLocaleString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const SideBadge = ({ side }: { side: string }) => (
  <StatusPill tone={side === "buy" ? "profit" : "loss"}>{side === "buy" ? "Achat" : "Vente"}</StatusPill>
);

const hasFrame = (row: TradeRow) => row.setupDetail !== null || row.violations.length > 0;

/** « Dans quel cadre » : what the system had proposed, and which rules the trade broke. */
function FramePills({ row }: { row: TradeRow }) {
  if (!hasFrame(row)) {
    return <span className="text-muted-foreground">—</span>;
  }
  return (
    <span className="flex flex-wrap gap-1">
      {row.setupDetail && (
        <span title={row.setupDetail}>
          <StatusPill tone="info">S01</StatusPill>
        </span>
      )}
      {row.violations.map((violation) => (
        <span key={violation.type} title={violation.detail}>
          <StatusPill tone="loss">{VIOLATION_LABELS[violation.type]}</StatusPill>
        </span>
      ))}
    </span>
  );
}

/** T05: a link, not a button — the capture is a fact recorded when the position opened. Nothing when there is none. */
const CaptureLink = ({ row }: { row: TradeRow }) =>
  row.trade.hasCapture ? (
    <Link
      href={`/journal/${row.trade.brokerPositionId}`}
      className="text-xs text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
    >
      Capture →
    </Link>
  ) : null;

const rLabel = (row: TradeRow) => (row.r === null ? "—" : row.r.toFixed(2));

const COLUMNS: Column<TradeRow>[] = [
  {
    key: "closed",
    header: "Clôturé",
    cell: (row) => <span className="text-muted-foreground">{formatClosedAt(row.trade.closedAt)}</span>,
  },
  { key: "symbol", header: "Symbole", cell: (row) => <span className="font-medium">{row.trade.symbol}</span> },
  { key: "side", header: "Sens", cell: (row) => <SideBadge side={row.trade.side} /> },
  { key: "volume", header: "Volume", align: "right", cell: (row) => row.trade.volume.toFixed(2) },
  {
    key: "entry",
    header: "Entrée",
    align: "right",
    cell: (row) => (row.trade.entryPrice === null ? "—" : formatQuote(row.trade.entryPrice)),
  },
  { key: "exit", header: "Sortie", align: "right", cell: (row) => formatQuote(row.trade.exitPrice) },
  {
    key: "r",
    header: "R",
    align: "right",
    cell: (row) => (
      <span className={row.r === null ? "text-muted-foreground" : pnlClass(row.r)}>{rLabel(row)}</span>
    ),
  },
  {
    key: "pnl",
    header: "P&L",
    align: "right",
    cell: (row) => (
      <span className={cn("font-medium", pnlClass(row.trade.realizedPnl))}>{formatSignedMoney(row.trade.realizedPnl)}</span>
    ),
  },
  {
    key: "duration",
    header: "Durée",
    align: "right",
    cell: (row) => <span className="text-muted-foreground">{row.duration}</span>,
  },
  { key: "frame", header: "Cadre", className: "min-w-44 whitespace-normal", cell: (row) => <FramePills row={row} /> },
  { key: "capture", header: "", align: "right", cell: (row) => <CaptureLink row={row} /> },
];

/**
 * The trades of the period: a dark-header table from `md` up, one card per
 * trade below (ADR 0017). The table scrolls inside its container when the
 * screen is narrower than its eleven columns — never the page.
 */
export function TradesTable({ rows }: { rows: TradeRow[] }) {
  return (
    <DataList
      rows={rows}
      columns={COLUMNS}
      rowKey={(row) => row.trade.brokerPositionId}
      mobileCard={(row) => (
        <>
          <MobileCardHeader
            name={row.trade.symbol}
            subtitle={formatClosedAt(row.trade.closedAt)}
            badge={<SideBadge side={row.trade.side} />}
          />
          <MobileFields
            fields={[
              { label: "Volume", value: row.trade.volume.toFixed(2) },
              { label: "Entrée", value: row.trade.entryPrice === null ? "—" : formatQuote(row.trade.entryPrice) },
              { label: "Sortie", value: formatQuote(row.trade.exitPrice) },
              {
                label: "P&L",
                value: <span className={pnlClass(row.trade.realizedPnl)}>{formatSignedMoney(row.trade.realizedPnl)}</span>,
              },
              { label: "R", value: <span className={row.r === null ? undefined : pnlClass(row.r)}>{rLabel(row)}</span> },
              { label: "Durée", value: row.duration },
            ]}
          />
          {(hasFrame(row) || row.trade.hasCapture) && (
            <div className="mt-3 flex items-center justify-between gap-3 text-xs">
              {hasFrame(row) ? <FramePills row={row} /> : <span />}
              <CaptureLink row={row} />
            </div>
          )}
        </>
      )}
    />
  );
}
