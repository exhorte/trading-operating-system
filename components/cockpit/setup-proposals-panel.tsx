"use client";

import { useEffect, useState } from "react";
import { backendHttpBase } from "@/lib/realtime/backend-url";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";

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

const REFRESH_MS = 30_000;
const LOOKBACK_MS = 24 * 60 * 60 * 1000;

function formatTime(iso: string): string {
  return new Date(iso).toISOString().slice(11, 16); // HH:mm UTC
}

/**
 * EA-02 — the instrument of measurement, not a signal screen: it exists to
 * compare the machine to the trader, never to say what to do. No P&L, win
 * rate, or any performance figure anywhere here (ADR 0011) — only what was
 * proposed, and why not when it wasn't.
 */
export function SetupProposalsPanel() {
  const [rows, setRows] = useState<SetupProposalRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const since = new Date(Date.now() - LOOKBACK_MS).toISOString();
        const res = await fetch(`${backendHttpBase()}/api/setup-proposals?since=${encodeURIComponent(since)}`);
        if (!res.ok) {
          throw new Error(`setup-proposals fetch failed (${res.status})`);
        }
        const data = (await res.json()) as SetupProposalRow[];
        if (!cancelled) {
          setRows(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "fetch failed");
        }
      }
    }

    load();
    const interval = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (error) {
    return (
      <Card title="S01 — Setup proposals (OBSERVE)">
        <p className="text-xs text-loss">{error}</p>
      </Card>
    );
  }

  if (rows === null) {
    return (
      <Card title="S01 — Setup proposals (OBSERVE)">
        <Skeleton className="h-40" />
      </Card>
    );
  }

  return (
    <Card
      title="S01 — Setup proposals (OBSERVE)"
      actions={<span className="text-[11px] text-muted">last 24h, no execution</span>}
    >
      {rows.length === 0 ? (
        <p className="text-xs text-muted">No evaluation recorded yet.</p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {rows.map((row) => (
            <div
              key={`${row.symbol}-${row.eventAt}`}
              className="flex items-center gap-2 border-b border-border/50 py-1 text-xs last:border-0"
            >
              <span className="tnum w-10 text-muted">{formatTime(row.eventAt)}</span>
              <span className="w-16 font-medium">{row.symbol}</span>
              {row.status === "proposed" ? (
                <>
                  <StatusPill tone="accent">{row.side}</StatusPill>
                  <span className="tnum text-muted">
                    entry {row.entryPrice} · SL {row.stopLoss} · TP {row.takeProfit} · c={row.costRatio?.toFixed(2)}{" "}
                    · R:R {row.riskRewardRatio?.toFixed(1)}
                  </span>
                </>
              ) : (
                <>
                  <StatusPill tone="muted">{row.stage}</StatusPill>
                  <span className="truncate text-muted">{row.detail}</span>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
