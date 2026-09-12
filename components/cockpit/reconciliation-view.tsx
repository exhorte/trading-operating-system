"use client";

import { useEffect, useMemo, useState } from "react";
import { backendHttpBase } from "@/lib/realtime/backend-url";
import { useCockpit } from "@/lib/realtime/provider";
import { reconcile, type ReconciliationRow } from "@/lib/setup/reconciliation";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import type { Side } from "@/lib/domain/primitives";

interface SetupProposalRow {
  symbol: string;
  eventAt: string;
  status: "proposed" | "blocked";
  side: Side | null;
}

interface ClosedTradeRow {
  brokerPositionId: string;
  symbol: string;
  side: Side;
  openedAt: string;
}

/** How close a trade's open time must be to a proposal's detection time to
 * count as the same trade — EA-02 prompt: "un trade pris trois minutes
 * après une proposition... est le même trade." Provisional, adjustable
 * after observation, same status as the killzone hours (lib/setup/preconditions.ts). */
const TOLERANCE_MINUTES = 5;
const LOOKBACK_MS = 7 * 24 * 60 * 60 * 1000;

const CLASS_LABEL: Record<ReconciliationRow["class"], string> = {
  PROPOSE_ET_PRIS: "Proposé et pris",
  PROPOSE_ET_REFUSE: "Proposé et refusé",
  PRIS_SANS_PROPOSITION: "Pris sans proposition",
};

const CLASS_TONE: Record<ReconciliationRow["class"], "profit" | "warning" | "loss"> = {
  PROPOSE_ET_PRIS: "profit",
  PROPOSE_ET_REFUSE: "warning",
  PRIS_SANS_PROPOSITION: "loss",
};

/**
 * EA-02 — machine/human agreement, the third and decisive check for S01's
 * success criterion (ADR 0011: the unit tests say the geometry is right,
 * the replay bench says where it fires, THIS says it's the strategy
 * actually traded). No P&L, no win rate: only the three classes.
 */
export function ReconciliationView() {
  const { account } = useCockpit();
  const accountId = account?.accountId ?? null;

  const [proposals, setProposals] = useState<SetupProposalRow[] | null>(null);
  const [trades, setTrades] = useState<ClosedTradeRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!accountId) {
      return;
    }
    let cancelled = false;

    async function load() {
      try {
        const base = backendHttpBase();
        const since = new Date(Date.now() - LOOKBACK_MS).toISOString();
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
          setProposals(proposalRows);
          setTrades(tradeRows);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "fetch failed");
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [accountId]);

  const rows = useMemo(() => {
    if (proposals === null || trades === null) {
      return null;
    }
    return reconcile(
      proposals.filter((p) => p.status === "proposed" && p.side !== null).map((p) => ({
        symbol: p.symbol,
        side: p.side as Side,
        detectedAt: p.eventAt,
      })),
      trades,
      TOLERANCE_MINUTES,
    );
  }, [proposals, trades]);

  if (!accountId) {
    return null;
  }
  if (error) {
    return (
      <Card title="Rapprochement — machine vs. réel">
        <p className="text-xs text-loss">{error}</p>
      </Card>
    );
  }
  if (rows === null) {
    return (
      <Card title="Rapprochement — machine vs. réel">
        <Skeleton className="h-40" />
      </Card>
    );
  }

  const counts = rows.reduce(
    (acc, r) => ({ ...acc, [r.class]: acc[r.class] + 1 }),
    { PROPOSE_ET_PRIS: 0, PROPOSE_ET_REFUSE: 0, PRIS_SANS_PROPOSITION: 0 } as Record<
      ReconciliationRow["class"],
      number
    >,
  );

  return (
    <Card title="Rapprochement — machine vs. réel" actions={<span className="text-[11px] text-muted">7 jours, aucune métrique de performance</span>}>
      <div className="mb-3 flex gap-2">
        {(Object.keys(CLASS_LABEL) as ReconciliationRow["class"][]).map((cls) => (
          <StatusPill key={cls} tone={CLASS_TONE[cls]}>
            {CLASS_LABEL[cls]} ({counts[cls]})
          </StatusPill>
        ))}
      </div>
      {rows.length === 0 ? (
        <p className="text-xs text-muted">Rien à rapprocher sur cette fenêtre.</p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {rows.map((row, i) => (
            <div
              key={`${row.class}-${row.brokerPositionId ?? row.proposalDetectedAt}-${i}`}
              className="flex items-center gap-2 border-b border-border/50 py-1 text-xs last:border-0"
            >
              <StatusPill tone={CLASS_TONE[row.class]}>{CLASS_LABEL[row.class]}</StatusPill>
              <span className="w-16 font-medium">{row.symbol}</span>
              <span className="text-muted">{row.side}</span>
              <span className="tnum text-muted">
                {row.proposalDetectedAt && `proposé ${formatTime(row.proposalDetectedAt)}`}
                {row.proposalDetectedAt && row.tradeOpenedAt && " · "}
                {row.tradeOpenedAt && `ouvert ${formatTime(row.tradeOpenedAt)}`}
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function formatTime(iso: string): string {
  return new Date(iso).toISOString().slice(11, 16);
}
