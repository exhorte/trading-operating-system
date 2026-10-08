"use client";

import { useEffect, useMemo, useState } from "react";
import { CircleCheck, FlaskConical, GitCompareArrows, Handshake, OctagonX, ShieldQuestion } from "lucide-react";
import { backendHttpBase } from "@/lib/realtime/backend-url";
import { useCockpit } from "@/lib/realtime/provider";
import { reconcile, type ReconciliationRow } from "@/lib/setup/reconciliation";
import type { Side } from "@/lib/domain/primitives";
import { PageHeader, SectionHeading } from "@/components/shell/page-header";
import { screenAt } from "@/components/shell/nav";
import { Callout } from "@/components/ui/callout";
import { DataList, MobileCardHeader, MobileFields, type Column } from "@/components/ui/data-list";
import { HighlightBar, MetricPanel, MetricPanelItem } from "@/components/ui/metric-panel";
import { Skeleton } from "@/components/ui/skeleton";
import { SplitLayout } from "@/components/ui/split-layout";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

/** Shape of GET /api/setup-proposals (SetupProposalRepository.SetupProposalRow). */
interface SetupProposalRow {
  symbol: string;
  eventAt: string;
  status: "proposed" | "blocked";
  stage: string | null;
  detail: string | null;
  side: "buy" | "sell" | null;
  sweptLevelKind: string | null;
  sweptLevelPrice: number | null;
  entryPrice: number | null;
  stopLoss: number | null;
  takeProfit: number | null;
  costRatio: number | null;
  riskRewardRatio: number | null;
}

interface ClosedTradeRow {
  brokerPositionId: string;
  symbol: string;
  side: Side;
  openedAt: string;
}

const REFRESH_MS = 30_000;
const PROPOSALS_LOOKBACK_MS = 24 * 60 * 60 * 1000;

/** How close a trade's open time must be to a proposal's detection time to
 * count as the same trade — EA-02 prompt: "un trade pris trois minutes
 * après une proposition... est le même trade." Provisional, adjustable
 * after observation, same status as the killzone hours (lib/setup/preconditions.ts). */
const TOLERANCE_MINUTES = 5;
const RECONCILIATION_LOOKBACK_MS = 7 * 24 * 60 * 60 * 1000;

type ReconciliationClass = ReconciliationRow["class"];

const CLASS_LABEL: Record<ReconciliationClass, string> = {
  PROPOSE_ET_PRIS: "Proposé et pris",
  PROPOSE_ET_REFUSE: "Proposé et refusé",
  PRIS_SANS_PROPOSITION: "Pris sans proposition",
};

const CLASS_TONE: Record<ReconciliationClass, PillTone> = {
  PROPOSE_ET_PRIS: "profit",
  PROPOSE_ET_REFUSE: "warning",
  PRIS_SANS_PROPOSITION: "loss",
};

function formatTime(iso: string): string {
  return new Date(iso).toISOString().slice(11, 16); // HH:mm UTC
}

/**
 * What the warning says. A refused connection reaches the screen as the
 * browser's own « Failed to fetch », which says nothing: name what happened —
 * the backend did not answer, or answered with this HTTP status.
 */
function describeFetchFailure(error: unknown): string {
  const status = error instanceof Error ? /\((\d{3})\)/.exec(error.message)?.[1] : undefined;
  return status ? `Le backend a répondu ${status}.` : "Le backend ne répond pas.";
}

const PROPOSAL_COLUMNS: Column<SetupProposalRow>[] = [
  { key: "time", header: "Heure (UTC)", cell: (r) => <span className="text-muted-foreground">{formatTime(r.eventAt)}</span> },
  { key: "symbol", header: "Symbole", cell: (r) => <span className="font-medium">{r.symbol}</span> },
  {
    key: "result",
    header: "Résultat",
    cell: (r) =>
      r.status === "proposed" ? (
        <StatusPill tone="accent">{r.side}</StatusPill>
      ) : (
        <StatusPill tone="muted">{r.stage}</StatusPill>
      ),
  },
  {
    key: "detail",
    header: "Détail",
    className: "text-muted-foreground",
    cell: (r) =>
      r.status === "proposed"
        ? `entry ${r.entryPrice} · SL ${r.stopLoss} · TP ${r.takeProfit} · c=${r.costRatio?.toFixed(2)} · R:R ${r.riskRewardRatio?.toFixed(1)}`
        : r.detail,
  },
];

const RECONCILIATION_COLUMNS: Column<ReconciliationRow>[] = [
  { key: "class", header: "Classe", cell: (r) => <StatusPill tone={CLASS_TONE[r.class]}>{CLASS_LABEL[r.class]}</StatusPill> },
  { key: "symbol", header: "Symbole", cell: (r) => <span className="font-medium">{r.symbol}</span> },
  { key: "side", header: "Sens", cell: (r) => <span className="text-muted-foreground">{r.side}</span> },
  {
    key: "proposed",
    header: "Proposé",
    cell: (r) => <span className="text-muted-foreground">{r.proposalDetectedAt ? formatTime(r.proposalDetectedAt) : "—"}</span>,
  },
  {
    key: "opened",
    header: "Ouvert",
    cell: (r) => <span className="text-muted-foreground">{r.tradeOpenedAt ? formatTime(r.tradeOpenedAt) : "—"}</span>,
  },
];

/**
 * EA-02 — the instrument of measurement (S01, « Critère de réussite »). Not a
 * signal screen: it exists to compare the machine to the trader, never to say
 * what to do. No P&L, win rate, or any performance figure anywhere here
 * (ADR 0011) — only what was proposed, why not when it wasn't, and the three
 * classes of machine/human agreement (the third and decisive check: the unit
 * tests say the geometry is right, the replay bench says where it fires, THIS
 * says it is the strategy actually traded).
 *
 * The page owns both fetches so the dark panel can count what the lists show.
 */
export function SetupsScreen() {
  const { account } = useCockpit();
  const accountId = account?.accountId ?? null;

  const [proposals, setProposals] = useState<SetupProposalRow[] | null>(null);
  const [proposalsError, setProposalsError] = useState<string | null>(null);

  const [weekProposals, setWeekProposals] = useState<SetupProposalRow[] | null>(null);
  const [trades, setTrades] = useState<ClosedTradeRow[] | null>(null);
  const [reconciliationError, setReconciliationError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const since = new Date(Date.now() - PROPOSALS_LOOKBACK_MS).toISOString();
        const res = await fetch(`${backendHttpBase()}/api/setup-proposals?since=${encodeURIComponent(since)}`);
        if (!res.ok) {
          throw new Error(`setup-proposals fetch failed (${res.status})`);
        }
        const data = (await res.json()) as SetupProposalRow[];
        if (!cancelled) {
          setProposals(data);
          setProposalsError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setProposalsError(describeFetchFailure(err));
        }
      }
    }

    void load();
    const interval = setInterval(() => void load(), REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (!accountId) {
      return;
    }
    let cancelled = false;

    async function load() {
      try {
        const base = backendHttpBase();
        const since = new Date(Date.now() - RECONCILIATION_LOOKBACK_MS).toISOString();
        const now = new Date().toISOString();

        const [proposalsRes, tradesRes] = await Promise.all([
          fetch(`${base}/api/setup-proposals?since=${encodeURIComponent(since)}`),
          fetch(
            `${base}/api/trades/closed?accountId=${encodeURIComponent(accountId!)}` +
              `&from=${encodeURIComponent(since)}&to=${encodeURIComponent(now)}`,
          ),
        ]);
        if (!proposalsRes.ok || !tradesRes.ok) {
          throw new Error("reconciliation fetch failed");
        }
        const proposalRows = (await proposalsRes.json()) as SetupProposalRow[];
        const tradeRows = (await tradesRes.json()) as ClosedTradeRow[];
        if (!cancelled) {
          setWeekProposals(proposalRows);
          setTrades(tradeRows);
          setReconciliationError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setReconciliationError(describeFetchFailure(err));
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [accountId]);

  const reconciliation = useMemo(() => {
    if (weekProposals === null || trades === null) {
      return null;
    }
    return reconcile(
      weekProposals
        .filter((p) => p.status === "proposed" && p.side !== null)
        .map((p) => ({ symbol: p.symbol, side: p.side as Side, detectedAt: p.eventAt })),
      trades,
      TOLERANCE_MINUTES,
    );
  }, [weekProposals, trades]);

  const counts = useMemo(() => {
    const result: Record<ReconciliationClass, number> = {
      PROPOSE_ET_PRIS: 0,
      PROPOSE_ET_REFUSE: 0,
      PRIS_SANS_PROPOSITION: 0,
    };
    for (const row of reconciliation ?? []) {
      result[row.class] += 1;
    }
    return result;
  }, [reconciliation]);

  const proposed = proposals?.filter((p) => p.status === "proposed").length ?? 0;
  const blocked = proposals?.filter((p) => p.status === "blocked").length ?? 0;
  const measured = reconciliation !== null;

  return (
    <div className="flex flex-col gap-10">
      <SplitLayout
        main={
          <>
            <PageHeader screen={screenAt("/setups")} />
            <Callout title="Un instrument de mesure, pas un écran de signaux">
              Aucun bouton n&apos;envoie quoi que ce soit, et aucun résultat (P&amp;L, taux de réussite) n&apos;y figure :
              seulement ce qui a été proposé, pourquoi pas quand ça ne l&apos;a pas été, et ce que j&apos;ai réellement
              pris (ADR 0011).
            </Callout>
          </>
        }
        aside={
          <>
            <HighlightBar
              icon={FlaskConical}
              value={proposals ? String(proposals.length) : "—"}
              label="évaluations de S01"
              aside={<span className="text-xs text-panel-muted">dernières 24 h, aucune exécution</span>}
            />
            <MetricPanel>
              <MetricPanelItem
                label="Propositions"
                value={proposals ? String(proposed) : "—"}
                hint="S01 en OBSERVE : rien n'est exécuté"
                icon={CircleCheck}
              />
              <MetricPanelItem
                label="Évaluations bloquées"
                value={proposals ? String(blocked) : "—"}
                hint="la répartition des raisons est la mesure"
                icon={OctagonX}
              />
              <MetricPanelItem
                label="Proposé et pris"
                value={measured ? String(counts.PROPOSE_ET_PRIS) : "—"}
                tone={measured && counts.PROPOSE_ET_PRIS > 0 ? "success" : undefined}
                hint="sur 7 jours — la machine et moi d'accord"
                icon={Handshake}
                solidIcon
              />
              <MetricPanelItem
                label="Pris sans proposition"
                value={measured ? String(counts.PRIS_SANS_PROPOSITION) : "—"}
                tone={measured && counts.PRIS_SANS_PROPOSITION > 0 ? "destructive" : undefined}
                hint={`sur 7 jours · proposé et refusé : ${measured ? counts.PROPOSE_ET_REFUSE : "—"}`}
                icon={ShieldQuestion}
              />
            </MetricPanel>
          </>
        }
      />

      <section className="flex flex-col gap-4">
        <SectionHeading
          title="S01 — Propositions (OBSERVE)"
          subtitle="dernières 24 h, aucune exécution"
          icon={FlaskConical}
        />
        {proposalsError ? (
          <Callout title="Propositions illisibles" variant="warning">
            {proposalsError}
          </Callout>
        ) : proposals === null ? (
          <Skeleton className="h-40 rounded-xl" />
        ) : proposals.length === 0 ? (
          <p className="rounded-xl border border-dashed py-8 text-center text-sm text-muted-foreground">
            Aucune évaluation enregistrée pour l&apos;instant.
          </p>
        ) : (
          <DataList
            rows={proposals}
            columns={PROPOSAL_COLUMNS}
            rowKey={(r) => `${r.symbol}-${r.eventAt}`}
            mobileCard={(r) => (
              <>
                <MobileCardHeader
                  name={r.symbol}
                  subtitle={`${formatTime(r.eventAt)} UTC`}
                  badge={
                    r.status === "proposed" ? (
                      <StatusPill tone="accent">{r.side}</StatusPill>
                    ) : (
                      <StatusPill tone="muted">{r.stage}</StatusPill>
                    )
                  }
                />
                <p className="mt-3 text-xs text-muted-foreground">
                  {r.status === "proposed"
                    ? `entry ${r.entryPrice} · SL ${r.stopLoss} · TP ${r.takeProfit} · c=${r.costRatio?.toFixed(2)} · R:R ${r.riskRewardRatio?.toFixed(1)}`
                    : r.detail}
                </p>
              </>
            )}
          />
        )}
      </section>

      {accountId && (
        <section className="flex flex-col gap-4">
          <SectionHeading
            title="Rapprochement — machine vs. réel"
            subtitle="7 jours, aucune métrique de performance"
            icon={GitCompareArrows}
            actions={
              measured ? (
                <ul className="flex flex-wrap gap-1.5" aria-label="Décompte par classe">
                  {(Object.keys(CLASS_LABEL) as ReconciliationClass[]).map((cls) => (
                    <li key={cls}>
                      <StatusPill tone={CLASS_TONE[cls]}>
                        {CLASS_LABEL[cls]} ({counts[cls]})
                      </StatusPill>
                    </li>
                  ))}
                </ul>
              ) : undefined
            }
          />
          {reconciliationError ? (
            <Callout title="Rapprochement illisible" variant="warning">
              {reconciliationError}
            </Callout>
          ) : reconciliation === null ? (
            <Skeleton className="h-40 rounded-xl" />
          ) : reconciliation.length === 0 ? (
            <p className="rounded-xl border border-dashed py-8 text-center text-sm text-muted-foreground">
              Rien à rapprocher sur cette fenêtre.
            </p>
          ) : (
            <DataList
              rows={reconciliation}
              columns={RECONCILIATION_COLUMNS}
              rowKey={(r) => `${r.class}-${r.brokerPositionId ?? r.proposalDetectedAt}-${r.symbol}`}
              mobileCard={(r) => (
                <>
                  <MobileCardHeader
                    name={r.symbol}
                    subtitle={r.side}
                    badge={<StatusPill tone={CLASS_TONE[r.class]}>{CLASS_LABEL[r.class]}</StatusPill>}
                  />
                  <MobileFields
                    fields={[
                      { label: "Proposé", value: r.proposalDetectedAt ? formatTime(r.proposalDetectedAt) : "—" },
                      { label: "Ouvert", value: r.tradeOpenedAt ? formatTime(r.tradeOpenedAt) : "—" },
                    ]}
                  />
                </>
              )}
            />
          )}
        </section>
      )}
    </div>
  );
}
