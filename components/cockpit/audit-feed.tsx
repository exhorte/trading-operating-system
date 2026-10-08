"use client";

import { useEffect, useMemo, useState } from "react";
import { ScrollText } from "lucide-react";
import { backendHttpBase } from "@/lib/realtime/backend-url";
import { formatClockTime } from "@/lib/format";
import { SectionHeading } from "@/components/shell/page-header";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { DataList, MobileCardHeader, MobileFields, type Column } from "@/components/ui/data-list";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";

/** One row of GET /api/audit/recent (AuditRepository.RecentAsync). */
interface AuditEntry {
  messageId: string;
  correlationId: string;
  type: string;
  source: string;
  sentAt: string;
}

const LIMIT = 50;
const PREVIEW_ROWS = 12;

const COLUMNS: Column<AuditEntry>[] = [
  { key: "type", header: "Type", cell: (e) => <span className="font-medium">{e.type}</span> },
  { key: "source", header: "Source", cell: (e) => <span className="text-muted-foreground">{e.source}</span> },
  { key: "time", header: "Heure", align: "right", cell: (e) => <span className="text-muted-foreground">{formatClockTime(e.sentAt)}</span> },
];

/**
 * The envelope audit trail, on screen for the first time.
 *
 * GET /api/audit/recent has existed since the persistence slice and had zero
 * frontend consumers as of 2026-09-20 — a system whose whole claim is that
 * every decision is auditable was keeping its audit trail behind curl. It is
 * every envelope the gateway persisted, newest first, which is also the
 * fastest way to see that the chain is alive at all.
 *
 * Not account-scoped (the table is the raw envelope log), so it renders even
 * when no account is connected — including against the mock realtime source,
 * where it is the one panel still showing real machine traffic.
 */
export function AuditFeed() {
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const res = await fetch(`${backendHttpBase()}/api/audit/recent?limit=${LIMIT}`);
        if (cancelled) {
          return;
        }
        if (!res.ok) {
          setFailed(true);
          return;
        }
        setEntries((await res.json()) as AuditEntry[]);
      } catch {
        if (!cancelled) {
          setFailed(true);
        }
      }
    }

    void load();
    const interval = setInterval(() => void load(), 15_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  /** 50 rows of the same event type is a wall; the tally makes it a fact. */
  const tally = useMemo(() => {
    if (!entries) {
      return [];
    }
    const counts = new Map<string, number>();
    for (const entry of entries) {
      counts.set(entry.type, (counts.get(entry.type) ?? 0) + 1);
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [entries]);

  const heading = (actions?: React.ReactNode) => (
    <SectionHeading
      title="Piste d'audit"
      subtitle="chaque enveloppe que le backend a persistée, la plus récente en premier"
      icon={ScrollText}
      actions={actions}
    />
  );

  if (failed) {
    return (
      <section className="flex flex-col gap-4">
        {heading(<StatusPill tone="loss">indisponible</StatusPill>)}
        <Callout title="Piste d'audit indisponible" variant="warning">
          <code className="text-foreground">/api/audit/recent</code> ne répond pas. Le backend est-il démarré ?{" "}
          <code className="text-foreground">docker ps</code> doit montrer{" "}
          <code className="text-foreground">tradingos-backend</code> et{" "}
          <code className="text-foreground">tradingos-timescaledb</code>.
        </Callout>
      </section>
    );
  }

  if (!entries) {
    return (
      <section className="flex flex-col gap-4">
        {heading()}
        <Skeleton className="h-64 rounded-xl" />
      </section>
    );
  }

  const visible = showAll ? entries : entries.slice(0, PREVIEW_ROWS);

  return (
    <section className="flex flex-col gap-4">
      {heading(<span className="text-sm text-muted-foreground">{entries.length} dernières enveloppes</span>)}
      {entries.length === 0 ? (
        <p className="rounded-xl border border-dashed px-6 py-8 text-center text-sm text-muted-foreground">
          Aucune enveloppe persistée. La chaîne temps réel n&apos;a rien écrit — observer MT5 arrêté, ou écriture en
          base coupée.
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
            rowKey={(e) => e.messageId}
            mobileCard={(e) => (
              <>
                <MobileCardHeader name={e.type} subtitle={e.source} />
                <MobileFields fields={[{ label: "Heure", value: formatClockTime(e.sentAt) }]} />
              </>
            )}
          />
          {entries.length > PREVIEW_ROWS && (
            <Button variant="outline" size="sm" className="self-center" onClick={() => setShowAll((value) => !value)}>
              {showAll ? "Réduire" : `Afficher les ${entries.length} enveloppes`}
            </Button>
          )}
        </>
      )}
    </section>
  );
}
