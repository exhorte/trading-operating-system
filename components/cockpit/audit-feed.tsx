"use client";

import { useMemo, useState } from "react";
import { ScrollText } from "lucide-react";
import type { EventRecord } from "@/lib/api/generated";
import { useApi } from "@/lib/api/use-api";
import { formatClockTime } from "@/lib/format";
import { SectionHeading } from "@/components/shell/page-header";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { DataList, MobileCardHeader, MobileFields, type Column } from "@/components/ui/data-list";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";

const LIMIT = 50;
const PREVIEW_ROWS = 12;
const POLL_MS = 15_000;

const COLUMNS: Column<EventRecord>[] = [
  { key: "type", header: "Type", cell: (e) => <span className="font-medium">{e.type}</span> },
  {
    key: "account",
    header: "Compte",
    cell: (e) => <span className="text-muted-foreground">{e.accountId ?? "—"}</span>,
  },
  {
    key: "time",
    header: "Heure",
    align: "right",
    cell: (e) => <span className="text-muted-foreground">{formatClockTime(e.occurredAt)}</span>,
  },
];

/**
 * The audit trail: every event the core recorded, newest first — which is also
 * the fastest way to see that the chain is alive at all. A system whose whole
 * claim is that every decision is auditable keeps its trail on screen, not
 * behind curl.
 *
 * Not account-scoped (the table is the raw event log), so it renders even
 * when no account is connected.
 */
export function AuditFeed() {
  const { data, error } = useApi("system_events", { query: { limit: LIMIT } }, { pollMs: POLL_MS });
  const [showAll, setShowAll] = useState(false);

  /** 50 rows of the same event type is a wall; the tally makes it a fact. */
  const tally = useMemo(() => {
    if (!data) {
      return [];
    }
    const counts = new Map<string, number>();
    for (const entry of data) {
      counts.set(entry.type, (counts.get(entry.type) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [data]);

  const heading = (actions?: React.ReactNode) => (
    <SectionHeading
      title="Piste d'audit"
      subtitle="chaque événement que le cœur a enregistré, le plus récent en premier"
      icon={ScrollText}
      actions={actions}
    />
  );

  if (error && !data) {
    return (
      <section className="flex flex-col gap-4">
        {heading(<StatusPill tone="loss">indisponible</StatusPill>)}
        <Callout title="Piste d'audit indisponible" variant="warning">
          {error.message}
        </Callout>
      </section>
    );
  }

  if (!data) {
    return (
      <section className="flex flex-col gap-4">
        {heading()}
        <Skeleton className="h-64 rounded-xl" />
      </section>
    );
  }

  const visible = showAll ? data : data.slice(0, PREVIEW_ROWS);

  return (
    <section className="flex flex-col gap-4">
      {heading(<span className="text-sm text-muted-foreground">{data.length} derniers événements</span>)}
      {data.length === 0 ? (
        <p className="rounded-xl border border-dashed px-6 py-8 text-center text-sm text-muted-foreground">
          Aucun événement enregistré. Le cœur n&apos;a rien écrit — vient-il de démarrer, ou la base est-elle
          injoignable ?
        </p>
      ) : (
        <>
          <ul className="flex flex-wrap gap-1.5" aria-label="Répartition par type">
            {tally.map(([type, count]) => (
              <li key={type} className="rounded-md border bg-muted/50 px-2 py-0.5 text-xs text-muted-foreground">
                {type} <span className="tnum font-medium text-foreground">{count}</span>
              </li>
            ))}
          </ul>
          <DataList
            rows={visible}
            columns={COLUMNS}
            rowKey={(e) => e.eventId}
            mobileCard={(e) => (
              <>
                <MobileCardHeader name={e.type} subtitle={e.accountId ?? "—"} />
                <MobileFields fields={[{ label: "Heure", value: formatClockTime(e.occurredAt) }]} />
              </>
            )}
          />
          {data.length > PREVIEW_ROWS && (
            <Button variant="outline" size="sm" className="self-center" onClick={() => setShowAll((value) => !value)}>
              {showAll ? "Réduire" : `Afficher les ${data.length} événements`}
            </Button>
          )}
        </>
      )}
    </section>
  );
}
