"use client";

import { useEffect, useState } from "react";
import { useCockpit } from "@/lib/realtime/provider";
import { backendHttpBase } from "@/lib/realtime/backend-url";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";

interface ExternalPosition {
  brokerPositionId: string;
  symbol: string;
  side: string;
  volume: number;
  magicNumber: number;
  knownCommandId: string | null;
  scannedAt: string;
}

interface Reconciliation {
  commandId: string;
  outcome: "executed" | "rejected" | "not_found";
  symbol: string | null;
  side: string | null;
  brokerPositionId: string | null;
  filledVolume: number | null;
  averagePrice: number | null;
  attempts: number;
  detail: string;
  reconciledAt: string;
}

/** Shape of GET /api/execution/divergence. */
interface Divergence {
  externalPositions: ExternalPosition[];
  reconciliations: Reconciliation[];
}

/**
 * EA-06 — execution-lifecycle divergence: positions the terminal reports
 * that this agent didn't open (EXTERNAL_POSITION, WARN — ADR 0010 magic
 * number isolation; already counted in the agent's local exposure barrier,
 * this only attributes it), and any commandId the agent had to resolve
 * after the fact because it was left UNKNOWN (ADR 0010: written before
 * OrderSend, never replayed). This page's old placeholder pointed live P&L
 * at the Command Center and reserved this one for exactly this — pending
 * commands, broker errors, reconciliation state.
 */
export default function PositionsPage() {
  const { account } = useCockpit();
  const accountId = account?.accountId ?? null;

  const [data, setData] = useState<Divergence | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!accountId) {
      return;
    }
    let cancelled = false;

    async function load() {
      try {
        const base = backendHttpBase();
        const res = await fetch(`${base}/api/execution/divergence?accountId=${encodeURIComponent(accountId!)}`);
        if (!res.ok) {
          throw new Error("divergence fetch failed");
        }
        const body = (await res.json()) as Divergence;
        if (!cancelled) {
          setData(body);
        }
      } catch {
        if (!cancelled) {
          setError("Could not load execution divergence.");
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [accountId]);

  if (!accountId) {
    return (
      <Card title="Execution divergence">
        <Skeleton className="h-48" />
      </Card>
    );
  }

  if (error) {
    return <EmptyState title="No divergence data" description={error} hint="EA-06" />;
  }

  if (!data) {
    return (
      <Card title="Execution divergence">
        <Skeleton className="h-48" />
      </Card>
    );
  }

  const unresolved = data.reconciliations.filter((r) => r.outcome === "not_found");
  const resolved = data.reconciliations.filter((r) => r.outcome !== "not_found");

  return (
    <div className="flex flex-col gap-4">
      <Card title="External positions">
        {data.externalPositions.length === 0 ? (
          <p className="text-sm text-muted">No position with a foreign magic number is currently open.</p>
        ) : (
          <ul className="flex flex-col gap-2 text-sm">
            {data.externalPositions.map((p) => (
              <li key={p.brokerPositionId} className="rounded border border-border p-2">
                <span className="font-medium">{p.symbol}</span> {p.side} {p.volume} lot — magic {p.magicNumber}
                <span className="block text-xs text-muted">
                  position {p.brokerPositionId} · last seen {new Date(p.scannedAt).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Unresolved commands">
        {unresolved.length === 0 ? (
          <p className="text-sm text-muted">Nothing left UNKNOWN.</p>
        ) : (
          <ul className="flex flex-col gap-2 text-sm">
            {unresolved.map((r) => (
              <li key={r.commandId} className="rounded border border-border p-2">
                <span className="font-medium">{r.commandId}</span> — {r.attempts} attempt(s)
                <span className="block text-xs text-muted">{r.detail}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {resolved.length > 0 && (
        <Card title="Recently reconciled">
          <ul className="flex flex-col gap-2 text-sm">
            {resolved.map((r) => (
              <li key={r.commandId} className="rounded border border-border p-2">
                <span className="font-medium">{r.commandId}</span> — {r.outcome}
                <span className="block text-xs text-muted">{r.detail}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
