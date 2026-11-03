"use client";

import { CloseAllButton } from "@/components/cockpit/close-all-button";
import type { ReactNode } from "react";
import { CircleAlert, CircleCheck, GitCompareArrows, Layers, TriangleAlert, TrendingUp, Unplug } from "lucide-react";
import type { Mismatch, MismatchKind } from "@/lib/api/generated";
import { useApi } from "@/lib/api/use-api";
import { useCockpit } from "@/lib/realtime/provider";
import { formatPercent, formatSignedMoney } from "@/lib/format";
import { PositionsTable } from "@/components/cockpit/positions-table";
import { PageHeader, SectionHeading } from "@/components/shell/page-header";
import { screenAt } from "@/components/shell/nav";
import { HighlightBar, MetricPanel, MetricPanelItem } from "@/components/ui/metric-panel";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { SplitLayout } from "@/components/ui/split-layout";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

/** One row of a divergence list — the same soft tile everywhere on the page. */
function Row({ children }: { children: ReactNode }) {
  return <li className="rounded-lg border bg-muted/40 px-3.5 py-3">{children}</li>;
}

const KIND_LABELS: Record<MismatchKind, string> = {
  ACCOUNT_MISMATCH: "Compte",
  POSITION_MISMATCH: "Position",
  ORDER_MISMATCH: "Ordre",
  SYMBOL_MISMATCH: "Symbole",
  UNKNOWN_EXECUTION: "Exécution inconnue",
  MISSING_POSITION: "Position manquante",
  UNEXPECTED_POSITION: "Position inattendue",
};

const SEVERITY_TONES: Record<Mismatch["severity"], PillTone> = {
  info: "info",
  warning: "warning",
  critical: "loss",
};

const REFRESH_ON = [
  "execution.unknown",
  "execution.reconciled",
  "execution.reported",
  "reconciliation.completed",
  "position.opened",
  "position.closed",
] as const;

function MismatchRow({ mismatch }: { mismatch: Mismatch }) {
  return (
    <Row>
      <span className="flex items-center justify-between gap-2">
        <span className="font-medium">{KIND_LABELS[mismatch.kind]}</span>
        <StatusPill tone={SEVERITY_TONES[mismatch.severity]}>{mismatch.severity}</StatusPill>
      </span>
      <span className="mt-1 block text-muted-foreground">{mismatch.detail}</span>
      {(mismatch.positionId || mismatch.commandId) && (
        <span className="block text-xs text-muted-foreground">
          {mismatch.positionId ? `position ${mismatch.positionId}` : ""}
          {mismatch.positionId && mismatch.commandId ? " · " : ""}
          {mismatch.commandId ? `commande ${mismatch.commandId}` : ""}
        </span>
      )}
    </Row>
  );
}

/**
 * Execution-lifecycle divergence, as the core's reconciliation sees it: positions the
 * terminal reports that this system did not open (a position taken by hand is a warning — it
 * is counted in the exposure barrier, this only attributes it), anything that contradicts what
 * a command recorded (critical — something is trading that the record says should not), and
 * every command left in doubt after the fact (UNKNOWN is a first-class state: written before
 * anything is sent, never replayed, settled from the broker's own data — ADR 0010).
 *
 * Composition (ADR 0017): the divergences sit beside the dark panel of key figures; the open
 * positions get the full width below, where an eleven-column table can breathe.
 */
export default function PositionsPage() {
  const { account, positions, activeAccountId } = useCockpit();
  const { data, error } = useApi(
    "execution_state",
    activeAccountId ? { query: { accountId: activeAccountId } } : null,
    { refreshOn: REFRESH_ON, pollMs: 30_000 },
  );

  const loading = !activeAccountId || (!data && !error);
  const report = data?.reconciliation ?? null;
  const mismatches = report?.mismatches ?? [];
  const external = mismatches.filter((m) => m.external);
  const contradictions = mismatches.filter((m) => !m.external);
  const critical = contradictions.filter((m) => m.severity === "critical");
  const inDoubt = data?.inDoubt ?? [];
  const settled = (data?.recent ?? []).filter((c) => c.state === "RECONCILED");
  const openPnl = positions.reduce((sum, p) => sum + p.unrealizedPnl, 0);
  const unknownHint = loading ? "chargement…" : error ? "cœur injoignable" : undefined;

  let divergence: ReactNode;
  if (loading) {
    divergence = <Skeleton className="h-48 rounded-xl" />;
  } else if (error || !data) {
    divergence = (
      <Panel title="Divergence d'exécution" icon={GitCompareArrows} description="réconciliation">
        <p className="rounded-lg border border-dashed py-8 text-center text-sm text-muted-foreground">
          {error?.message ?? "Impossible de charger la divergence d'exécution."}
        </p>
      </Panel>
    );
  } else {
    divergence = (
      <>
        <Panel
          title="Positions hors système"
          icon={Unplug}
          description="ouvertes à la main dans MT5, pas par une commande de ce système"
        >
          {external.length === 0 ? (
            <p className="text-sm text-muted-foreground">Aucune position étrangère n&apos;est ouverte.</p>
          ) : (
            <ul className="flex flex-col gap-2 text-sm">
              {external.map((m, i) => (
                <MismatchRow key={`${m.positionId ?? i}-${m.kind}`} mismatch={m} />
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Écarts avec ce que le système a envoyé" icon={TriangleAlert} description="comparaison avec le courtier">
          {report === null ? (
            <p className="text-sm text-muted-foreground">Aucune réconciliation n&apos;a encore tourné pour ce compte.</p>
          ) : !report.readable ? (
            <p className="text-sm text-destructive">
              Terminal illisible à la dernière réconciliation{report.error ? ` : ${report.error}` : ""} — rien n&apos;a pu
              être comparé.
            </p>
          ) : contradictions.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Rien ne contredit les commandes enregistrées ({report.positionsChecked} position(s) vérifiée(s)).
            </p>
          ) : (
            <ul className="flex flex-col gap-2 text-sm">
              {contradictions.map((m, i) => (
                <MismatchRow key={`${m.positionId ?? m.commandId ?? i}-${m.kind}`} mismatch={m} />
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Commandes en doute" icon={CircleAlert} description="UNKNOWN / RECONCILING en attente de règlement">
          {inDoubt.length === 0 ? (
            <p className="text-sm text-muted-foreground">Aucune commande n&apos;est restée dans le doute.</p>
          ) : (
            <ul className="flex flex-col gap-2 text-sm">
              {inDoubt.map((c) => (
                <Row key={c.request.commandId}>
                  <span className="font-medium">{c.request.commandId}</span> — {c.state}, {c.attempts} tentative(s)
                  <span className="block text-xs text-muted-foreground">{c.detail}</span>
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
                label="Positions hors système"
                value={data ? String(external.length) : "—"}
                tone={data && external.length > 0 ? "warning" : undefined}
                hint={unknownHint ?? "ouvertes à la main, hors de ce système"}
                icon={Unplug}
              />
              <MetricPanelItem
                label="Écarts critiques"
                value={data ? String(critical.length) : "—"}
                tone={data && critical.length > 0 ? "destructive" : undefined}
                hint={unknownHint ?? "positions que le registre dit ne pas exister"}
                icon={TriangleAlert}
              />
              <MetricPanelItem
                label="Commandes en doute"
                value={data ? String(inDoubt.length) : "—"}
                tone={data && inDoubt.length > 0 ? "destructive" : undefined}
                hint={unknownHint ?? "en attente de règlement"}
                icon={CircleAlert}
                solidIcon
              />
            </MetricPanel>
          </>
        }
      />

      <section className="flex flex-col gap-4">
        <SectionHeading title="Positions ouvertes" subtitle="suivies en direct" icon={Layers} actions={<CloseAllButton size="sm" />} />
        <PositionsTable />
      </section>

      {settled.length > 0 && (
        <Panel title="Réconciliées récemment" icon={CircleCheck}>
          <ul className="flex flex-col gap-2 text-sm">
            {settled.map((c) => (
              <Row key={c.request.commandId}>
                <span className="font-medium">{c.request.commandId}</span> — {c.state}
                <span className="block text-xs text-muted-foreground">{c.detail}</span>
              </Row>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
}
