"use client";

import { FileText } from "lucide-react";
import { cn } from "cn";
import type { ExecutionCommand } from "@/lib/api/generated";
import { COMMAND_STATE_TONES } from "@/lib/cockpit/command-state";
import { useCockpit, useIsDataUntrusted } from "@/lib/realtime/provider";
import { formatClockTime } from "@/lib/format";
import { SectionHeading } from "@/components/shell/page-header";
import { DataList, MobileCardHeader, MobileFields, type Column } from "@/components/ui/data-list";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";

const sideClass = (side: string | null) => (side === "buy" ? "text-success" : "text-destructive");

/** When the command last moved: the furthest point of its life that has a time. */
function lastChange(command: ExecutionCommand): string {
  return command.completedAt ?? command.acknowledgedAt ?? command.sentAt ?? command.createdAt;
}

function detailOf(command: ExecutionCommand): string {
  return command.detail || command.rejectCode || "";
}

const SideCell = ({ side }: { side: string | null }) =>
  side === null ? (
    <span className="text-muted-foreground">—</span>
  ) : (
    <span className={cn("font-medium", sideClass(side))}>{side.toUpperCase()}</span>
  );

const COLUMNS: Column<ExecutionCommand>[] = [
  { key: "time", header: "Heure", cell: (c) => <span className="text-muted-foreground">{formatClockTime(lastChange(c))}</span> },
  { key: "command", header: "Commande", cell: (c) => <span className="text-muted-foreground">{c.request.commandId}</span> },
  { key: "symbol", header: "Symbole", cell: (c) => <span className="font-medium">{c.request.symbol}</span> },
  { key: "side", header: "Sens", cell: (c) => <SideCell side={c.request.side} /> },
  { key: "status", header: "Statut", cell: (c) => <StatusPill tone={COMMAND_STATE_TONES[c.state]}>{c.state}</StatusPill> },
  {
    key: "detail",
    header: "Détail",
    className: "max-w-xs truncate whitespace-nowrap text-muted-foreground",
    cell: (c) => detailOf(c),
  },
];

/**
 * The last commands the core sent (or refused to send) to the execution agent,
 * with the state it holds for each — a command is a fact the core recorded
 * before anything left, so a refused one is here too, with its reason.
 */
export function ExecutionCommandsFeed() {
  const { commands, connection } = useCockpit();
  const untrusted = useIsDataUntrusted();

  return (
    <section className="flex flex-col gap-4">
      <SectionHeading
        title="Commandes d'exécution"
        subtitle="les six dernières commandes, avec l'état que le cœur leur donne"
        icon={FileText}
      />
      {connection === "connecting" ? (
        <Skeleton className="h-28 rounded-xl" />
      ) : commands.length === 0 ? (
        <p className="rounded-xl border border-dashed py-8 text-center text-sm text-muted-foreground">
          Aucune commande d&apos;exécution.
        </p>
      ) : (
        <div className={cn("transition-opacity", untrusted && "opacity-60")}>
          <DataList
            rows={commands.slice(0, 6)}
            columns={COLUMNS}
            rowKey={(c) => c.request.commandId}
            mobileCard={(c) => (
              <>
                <MobileCardHeader
                  name={c.request.symbol}
                  subtitle={c.request.commandId}
                  badge={<StatusPill tone={COMMAND_STATE_TONES[c.state]}>{c.state}</StatusPill>}
                />
                <MobileFields
                  fields={[
                    { label: "Heure", value: formatClockTime(lastChange(c)) },
                    { label: "Sens", value: <SideCell side={c.request.side} /> },
                  ]}
                />
                <p className="mt-3 text-xs text-muted-foreground">{detailOf(c)}</p>
              </>
            )}
          />
        </div>
      )}
    </section>
  );
}
