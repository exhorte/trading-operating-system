"use client";

import { FileText } from "lucide-react";
import { cn } from "cn";
import type { ExecutionReport } from "@/lib/contracts/snapshots";
import type { ExecutionReportStatus } from "@/lib/contracts/enums";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatClockTime } from "@/lib/format";
import { SectionHeading } from "@/components/shell/page-header";
import { DataList, MobileCardHeader, MobileFields, type Column } from "@/components/ui/data-list";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

const REPORT_TONES: Record<ExecutionReportStatus, PillTone> = {
  acknowledged: "info",
  submitted: "info",
  // Observe-mode outcome: deliberately NOT the "profit" fill tone.
  simulated: "accent",
  filled: "profit",
  partially_filled: "warning",
  failed: "loss",
  rejected: "loss",
  position_opened: "profit",
  position_modified: "info",
  position_closed: "muted",
};

const sideClass = (side: ExecutionReport["side"]) => (side === "buy" ? "text-success" : "text-destructive");

const COLUMNS: Column<ExecutionReport>[] = [
  { key: "time", header: "Heure", cell: (r) => <span className="text-muted-foreground">{formatClockTime(r.reportedAt)}</span> },
  { key: "command", header: "Commande", cell: (r) => <span className="text-muted-foreground">{r.commandId}</span> },
  { key: "symbol", header: "Symbole", cell: (r) => <span className="font-medium">{r.symbol}</span> },
  {
    key: "side",
    header: "Sens",
    cell: (r) => <span className={cn("font-medium", sideClass(r.side))}>{r.side.toUpperCase()}</span>,
  },
  { key: "status", header: "Statut", cell: (r) => <StatusPill tone={REPORT_TONES[r.status]}>{r.status}</StatusPill> },
  {
    key: "detail",
    header: "Détail",
    className: "max-w-xs truncate whitespace-nowrap text-muted-foreground",
    cell: (r) => r.detail,
  },
];

export function ExecutionReportsFeed() {
  const { executionReports, connection } = useCockpit();
  const untrusted = useIsDataUntrusted();

  return (
    <section className="flex flex-col gap-4">
      <SectionHeading
        title="Execution reports"
        subtitle="les six derniers retours de l'agent d'exécution"
        icon={FileText}
      />
      {connection === "connecting" ? (
        <Skeleton className="h-28 rounded-xl" />
      ) : executionReports.length === 0 ? (
        <p className="rounded-xl border border-dashed py-8 text-center text-sm text-muted-foreground">
          No execution reports.
        </p>
      ) : (
        <div className={cn("transition-opacity", untrusted && "opacity-60")}>
          <DataList
            rows={executionReports.slice(0, 6)}
            columns={COLUMNS}
            rowKey={(r) => r.reportId}
            mobileCard={(r) => (
              <>
                <MobileCardHeader
                  name={r.symbol}
                  subtitle={r.commandId}
                  badge={<StatusPill tone={REPORT_TONES[r.status]}>{r.status}</StatusPill>}
                />
                <MobileFields
                  fields={[
                    { label: "Heure", value: formatClockTime(r.reportedAt) },
                    { label: "Sens", value: <span className={sideClass(r.side)}>{r.side.toUpperCase()}</span> },
                  ]}
                />
                <p className="mt-3 text-xs text-muted-foreground">{r.detail}</p>
              </>
            )}
          />
        </div>
      )}
    </section>
  );
}
