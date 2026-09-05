"use client";

import type { ExecutionReportStatus } from "@/lib/contracts/enums";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatClockTime } from "@/lib/format";
import { Card } from "@/components/ui/card";
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
  position_opened: "profit",
  position_modified: "info",
  position_closed: "muted",
};

export function ExecutionReportsFeed() {
  const { executionReports, connection } = useCockpit();
  const untrusted = useIsDataUntrusted();

  if (connection === "connecting") {
    return (
      <Card title="Execution reports">
        <Skeleton className="h-28" />
      </Card>
    );
  }

  return (
    <Card title="Execution reports" untrusted={untrusted}>
      {executionReports.length === 0 ? (
        <p className="py-6 text-center text-xs text-muted">No execution reports.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {executionReports.slice(0, 6).map((report) => (
            <li
              key={report.reportId}
              className="flex items-center justify-between gap-2 rounded border border-border bg-surface-elevated px-2 py-1.5"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-xs">
                  <span className="tnum text-muted">{report.commandId}</span>
                  <span className="font-medium">{report.symbol}</span>
                  <span className={report.side === "buy" ? "text-profit" : "text-loss"}>
                    {report.side.toUpperCase()}
                  </span>
                </div>
                <p className="truncate text-[10px] text-muted">{report.detail}</p>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-0.5">
                <StatusPill tone={REPORT_TONES[report.status]}>{report.status}</StatusPill>
                <span className="tnum text-[10px] text-muted">
                  {formatClockTime(report.reportedAt)}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
