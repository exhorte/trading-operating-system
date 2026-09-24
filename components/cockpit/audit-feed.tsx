"use client";

import { useEffect, useMemo, useState } from "react";
import { backendHttpBase } from "@/lib/realtime/backend-url";
import { formatClockTime } from "@/lib/format";
import { Panel } from "@/components/ui/panel";
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

  if (failed) {
    return (
      <Panel title="Piste d'audit" actions={<StatusPill tone="loss">indisponible</StatusPill>}>
        <p className="text-xs text-muted-foreground">
          <code className="text-foreground">/api/audit/recent</code> ne répond pas. Le backend
          est-il démarré ? <code className="text-foreground">docker ps</code> doit montrer{" "}
          <code className="text-foreground">tradingos-backend</code> et{" "}
          <code className="text-foreground">tradingos-timescaledb</code>.
        </p>
      </Panel>
    );
  }

  if (!entries) {
    return (
      <Panel title="Piste d'audit">
        <Skeleton className="h-64" />
      </Panel>
    );
  }

  return (
    <Panel
      title="Piste d'audit"
      actions={
        <span className="text-xs text-muted-foreground">{entries.length} dernières enveloppes</span>
      }
    >
      {entries.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Aucune enveloppe persistée. La chaîne temps réel n&apos;a rien écrit — observer MT5
          arrêté, ou écriture en base coupée.
        </p>
      ) : (
        <>
          <div className="mb-2 flex flex-wrap gap-1">
            {tally.map(([type, count]) => (
              <span
                key={type}
                className="rounded border border-border bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground"
              >
                {type} <span className="tnum text-foreground">{count}</span>
              </span>
            ))}
          </div>
          <ul className="max-h-72 overflow-y-auto">
            {entries.map((entry) => (
              <li
                key={entry.messageId}
                className="flex items-center justify-between gap-2 border-t border-border py-1 text-xs first:border-t-0"
              >
                <span className="truncate text-foreground">{entry.type}</span>
                <span className="flex shrink-0 items-center gap-2 text-muted-foreground">
                  <span>{entry.source}</span>
                  <span className="tnum">{formatClockTime(entry.sentAt)}</span>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}
