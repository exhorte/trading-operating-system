"use client";

import { useEffect, useState, type ReactNode } from "react";
import { CircleAlert, CircleCheck, GitCompareArrows, Layers, TrendingUp, Unplug } from "lucide-react";
import { useCockpit } from "@/lib/realtime/provider";
import { backendHttpBase } from "@/lib/realtime/backend-url";
import { formatPercent, formatSignedMoney } from "@/lib/format";
import { PositionsTable } from "@/components/cockpit/positions-table";
import { PageHeader, SectionHeading } from "@/components/shell/page-header";
import { screenAt } from "@/components/shell/nav";
import { HighlightBar, MetricPanel, MetricPanelItem } from "@/components/ui/metric-panel";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { SplitLayout } from "@/components/ui/split-layout";

/** One row of a divergence list — the same soft tile everywhere on the page. */
function Row({ children }: { children: ReactNode }) {
  return <li className="rounded-lg border bg-muted/40 px-3.5 py-3">{children}</li>;
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
 *
 * Composition (ADR 0017): the divergences sit beside the dark panel of key
 * figures; the open positions get the full width below, where an
 * eleven-column table can breathe.
 */
export default function PositionsPage() {
  const { account, positions } = useCockpit();
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
          setError("Impossible de charger la divergence d'exécution.");
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [accountId]);

  const loading = !accountId || (!data && !error);
  const unresolved = data?.reconciliations.filter((r) => r.outcome === "not_found") ?? [];
  const resolved = data?.reconciliations.filter((r) => r.outcome !== "not_found") ?? [];
  const openPnl = positions.reduce((sum, p) => sum + p.unrealizedPnl, 0);
  const unknownHint = loading ? "chargement…" : error ? "backend injoignable" : undefined;

  let divergence: ReactNode;
  if (loading) {
    divergence = <Skeleton className="h-48 rounded-xl" />;
  } else if (error || !data) {
    divergence = (
      <Panel title="Divergence d'exécution" icon={GitCompareArrows} description="EA-06">
        <p className="rounded-lg border border-dashed py-8 text-center text-sm text-muted-foreground">
          {error ?? "Impossible de charger la divergence d'exécution."} Le backend répond-il ?
        </p>
      </Panel>
    );
  } else {
    divergence = (
      <>
        <Panel title="Positions externes" icon={Unplug} description="Magic number étranger à l'agent EA-05">
          {data.externalPositions.length === 0 ? (
            <p className="text-sm text-muted-foreground">Aucune position à magic number étranger n&apos;est ouverte.</p>
          ) : (
            <ul className="flex flex-col gap-2 text-sm">
              {data.externalPositions.map((p) => (
                <Row key={p.brokerPositionId}>
                  <span className="font-medium">{p.symbol}</span> {p.side} {p.volume} lot — magic {p.magicNumber}
                  <span className="block text-xs text-muted-foreground">
                    position {p.brokerPositionId} · vue pour la dernière fois le {new Date(p.scannedAt).toLocaleString("fr-FR")}
                  </span>
                </Row>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Commandes non résolues" icon={CircleAlert} description="UNKNOWN en attente de réconciliation">
          {unresolved.length === 0 ? (
            <p className="text-sm text-muted-foreground">Aucune commande n&apos;est restée UNKNOWN.</p>
          ) : (
            <ul className="flex flex-col gap-2 text-sm">
              {unresolved.map((r) => (
                <Row key={r.commandId}>
                  <span className="font-medium">{r.commandId}</span> — {r.attempts} tentative(s)
                  <span className="block text-xs text-muted-foreground">{r.detail}</span>
                </Row>
              ))}
            </ul>
          )}
        </Panel>
      </>
    );
  }

  return (
    <div className="flex flex-col gap-10">
      <SplitLayout
        main={
          <>
            <PageHeader screen={screenAt("/positions")} />
            {divergence}
          </>
        }
        aside={
          <>
            <HighlightBar
              icon={Layers}
              value={String(positions.length)}
              label="Positions ouvertes"
              aside={
                account ? (
                  <span className="text-xs text-panel-muted">risque ouvert {formatPercent(account.openRiskPercent)}</span>
                ) : undefined
              }
            />
            <MetricPanel>
              <MetricPanelItem
                label="P&L latent"
                value={formatSignedMoney(openPnl)}
                tone={openPnl >= 0 ? "success" : "destructive"}
                hint="somme des positions ouvertes"
                icon={TrendingUp}
              />
              <MetricPanelItem
                label="Positions externes"
                value={data ? String(data.externalPositions.length) : "—"}
                tone={data && data.externalPositions.length > 0 ? "warning" : undefined}
                hint={unknownHint ?? "magic number étranger à l'agent EA-05"}
                icon={Unplug}
              />
              <MetricPanelItem
                label="Commandes UNKNOWN"
                value={data ? String(unresolved.length) : "—"}
                tone={data && unresolved.length > 0 ? "destructive" : undefined}
                hint={unknownHint ?? "en attente de réconciliation"}
                icon={CircleAlert}
                solidIcon
              />
            </MetricPanel>
          </>
        }
      />

      <section className="flex flex-col gap-4">
        <SectionHeading title="Positions ouvertes" subtitle="suivies en direct" icon={Layers} />
        <PositionsTable />
      </section>

      {resolved.length > 0 && (
        <Panel title="Réconciliées récemment" icon={CircleCheck}>
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
