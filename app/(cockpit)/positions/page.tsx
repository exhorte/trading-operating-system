"use client";

import { useEffect, useState, type ReactNode } from "react";
import { CircleAlert, CircleCheck, GitCompareArrows, Unplug } from "lucide-react";
import { useCockpit } from "@/lib/realtime/provider";
import { backendHttpBase } from "@/lib/realtime/backend-url";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { PositionsTable } from "@/components/cockpit/positions-table";

/** One row of a divergence list — the same soft tile everywhere on the page. */
function Row({ children }: { children: ReactNode }) {
  return <li className="rounded-xl bg-muted/50 px-3.5 py-3 ring-1 ring-border">{children}</li>;
}

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

  // The open positions first — the half of this screen's question
  // (« qu'est-ce qui est ouvert ») that used to live on the Command Center
  // only — then whether they match what the system itself sent (EA-06).
  let divergence: ReactNode;
  if (!accountId || (!data && !error)) {
    divergence = (
      <Panel title="Divergence d'exécution" icon={GitCompareArrows}>
        <Skeleton className="h-40 rounded-xl" />
      </Panel>
    );
  } else if (error || !data) {
    divergence = (
      <Panel title="Divergence d'exécution" icon={GitCompareArrows} description="EA-06">
        <p className="rounded-xl border border-dashed border-border py-8 text-center text-sm text-muted-foreground">
          {error ?? "Could not load execution divergence."} Le backend répond-il ?
        </p>
      </Panel>
    );
  } else {
    const unresolved = data.reconciliations.filter((r) => r.outcome === "not_found");
    const resolved = data.reconciliations.filter((r) => r.outcome !== "not_found");
    divergence = (
      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="External positions" icon={Unplug} description="Magic number étranger à l'agent EA-05">
          {data.externalPositions.length === 0 ? (
            <p className="text-sm text-muted-foreground">No position with a foreign magic number is currently open.</p>
          ) : (
            <ul className="flex flex-col gap-2 text-sm">
              {data.externalPositions.map((p) => (
                <Row key={p.brokerPositionId}>
                  <span className="font-medium">{p.symbol}</span> {p.side} {p.volume} lot — magic {p.magicNumber}
                  <span className="block text-xs text-muted-foreground">
                    position {p.brokerPositionId} · last seen {new Date(p.scannedAt).toLocaleString()}
                  </span>
                </Row>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Unresolved commands" icon={CircleAlert} description="UNKNOWN en attente de réconciliation">
          {unresolved.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nothing left UNKNOWN.</p>
          ) : (
            <ul className="flex flex-col gap-2 text-sm">
              {unresolved.map((r) => (
                <Row key={r.commandId}>
                  <span className="font-medium">{r.commandId}</span> — {r.attempts} attempt(s)
                  <span className="block text-xs text-muted-foreground">{r.detail}</span>
                </Row>
              ))}
            </ul>
          )}
        </Panel>

        {resolved.length > 0 && (
          <Panel title="Recently reconciled" icon={CircleCheck} className="lg:col-span-2">
            <ul className="flex flex-col gap-2 text-sm">
              {resolved.map((r) => (
                <Row key={r.commandId}>
                  <span className="font-medium">{r.commandId}</span> — {r.outcome}
                  <span className="block text-xs text-muted-foreground">{r.detail}</span>
                </Row>
              ))}
            </ul>
          </Panel>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <PositionsTable showViewAll={false} />
      {divergence}
    </div>
  );
}
