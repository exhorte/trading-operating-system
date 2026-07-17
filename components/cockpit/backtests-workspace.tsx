"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

const BACKEND_BASE = (
  process.env.NEXT_PUBLIC_BACKEND_HUB_URL ?? "http://localhost:5080/hub/cockpit"
).replace("/hub/cockpit", "");

interface BacktestRun {
  runId: string;
  symbol: string;
  timeframe: string;
  engineVersion: string;
  config: string;
  fromTime: string;
  toTime: string;
  candleCount: number;
  signalCount: number;
  approvedCount: number;
  tradeCount: number;
  winCount: number;
  lossCount: number;
  timeoutCount: number;
  bothTouchCount: number;
  winRate: number;
  avgR: number;
  expectancyR: number;
  maxConsecLosses: number;
  cumulativeR: number;
  /** Locked out-of-sample trades excluded from every metric above (ADR 0013). */
  oosTradeCount: number;
  createdAt: string;
}

interface BacktestTrade {
  seq: number;
  signalTime: string;
  side: string;
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
  volume: number;
  outcome: string;
  bothTouch: boolean;
  rMultiple: number;
  barsHeld: number;
  exitPrice: number;
  score: number;
  reason: string;
}

const OUTCOME_TONES: Record<string, PillTone> = {
  win: "profit",
  loss: "loss",
  timeout: "muted",
};

function day(iso: string): string {
  return iso.slice(0, 10);
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded border border-border bg-surface-elevated px-2 py-1.5">
      <p className="text-[10px] uppercase tracking-wider text-muted">{label}</p>
      <p className={`tnum text-sm font-semibold ${tone ?? "text-foreground"}`}>{value}</p>
    </div>
  );
}

export function BacktestsWorkspace() {
  const [runs, setRuns] = useState<BacktestRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // Keyed by runId so trades from a previous selection never flash on the new
  // run, and so the effect only ever setState()s asynchronously.
  const [trades, setTrades] = useState<{ runId: string; list: BacktestTrade[] } | null>(null);

  useEffect(() => {
    fetch(`${BACKEND_BASE}/api/backtests`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((data: BacktestRun[]) => setRuns(data))
      .catch((err: Error) => setError(err.message));
  }, []);

  const selected = runs && runs.length > 0 ? runs.find((r) => r.runId === selectedId) ?? runs[0] : null;
  const selectedRunId = selected?.runId;

  useEffect(() => {
    if (!selectedRunId) {
      return;
    }
    let cancelled = false;
    fetch(`${BACKEND_BASE}/api/backtests/${selectedRunId}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((data: { trades: BacktestTrade[] }) => {
        if (!cancelled) setTrades({ runId: selectedRunId, list: data.trades });
      })
      .catch(() => {
        if (!cancelled) setTrades({ runId: selectedRunId, list: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [selectedRunId]);

  const currentTrades =
    trades && trades.runId === selectedRunId ? trades.list : null;

  if (error) {
    return (
      <EmptyState
        title="Backend unreachable"
        description={`Could not load backtest runs (${error}). Start the backend host and the database (context/backtesting/backtest_mvp.md).`}
        hint="docker compose up -d · dotnet run --project src/TradingOs.Host"
      />
    );
  }
  if (runs === null) {
    return <EmptyState title="Loading backtests…" description="Fetching runs from the backend." />;
  }
  if (runs.length === 0) {
    return (
      <EmptyState
        title="No backtest runs yet"
        description="Import history and run the backtester: python tools/mt5-observer/import_history.py, npx tsx scripts/import-candles.ts candles.jsonl, npx tsx scripts/backtest.ts."
        hint="Runbook: context/backtesting/backtest_mvp.md"
      />
    );
  }

  if (!selected) {
    return <EmptyState title="No backtest runs yet" description="Run the backtester to see results." />;
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
        Hypothesis testing only — engine {selected.engineVersion}. No spread, slippage or
        commissions; binary SL/TP exits; both-touch bars counted as losses (conservative).
        These numbers grade signal quality, never account performance.
      </p>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[320px_1fr]">
        <Card title={`Runs (${runs.length})`}>
          <ul className="flex flex-col gap-1">
            {runs.map((run) => {
              const active = selected.runId === run.runId;
              return (
                <li key={run.runId}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(run.runId)}
                    className={`w-full rounded border px-2 py-1.5 text-left ${
                      active
                        ? "border-accent/50 bg-accent/10"
                        : "border-border bg-surface-elevated hover:border-border-strong"
                    }`}
                  >
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-medium">
                        {run.symbol} {run.timeframe}
                      </span>
                      <span
                        className={`tnum ${run.cumulativeR >= 0 ? "text-profit" : "text-loss"}`}
                      >
                        {run.cumulativeR >= 0 ? "+" : ""}
                        {run.cumulativeR}R
                      </span>
                    </div>
                    <div className="mt-0.5 flex items-center justify-between text-[10px] text-muted">
                      <span>
                        {day(run.fromTime)} → {day(run.toTime)}
                      </span>
                      <span className="tnum">{run.tradeCount} trades</span>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        </Card>

        <div className="flex flex-col gap-3">
          <Card title={`Run ${selected.runId}`}>
            {selected.oosTradeCount > 0 && (
              <p className="mb-2 rounded border border-border bg-surface-elevated px-2 py-1.5 text-[11px] text-muted">
                🔒 {selected.oosTradeCount} out-of-sample trades reserved — every figure and the
                trade list below cover train+validation only, until the campaign-end{" "}
                <code>--unlock-oos</code> read (ADR 0013).
              </p>
            )}
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              <Metric label="Trades" value={`${selected.tradeCount} / ${selected.signalCount} signals`} />
              <Metric label="Win rate" value={`${selected.winRate}%`} />
              <Metric
                label="Expectancy"
                value={`${selected.expectancyR}R`}
                tone={selected.expectancyR >= 0 ? "text-profit" : "text-loss"}
              />
              <Metric
                label="Cumulative"
                value={`${selected.cumulativeR}R`}
                tone={selected.cumulativeR >= 0 ? "text-profit" : "text-loss"}
              />
              <Metric label="Avg R (decided)" value={`${selected.avgR}R`} />
              <Metric label="Max consec. losses" value={String(selected.maxConsecLosses)} />
              <Metric label="Timeouts" value={String(selected.timeoutCount)} />
              <Metric
                label="Both-touch bars"
                value={String(selected.bothTouchCount)}
                tone={selected.bothTouchCount > 0 ? "text-warning" : undefined}
              />
            </div>
            <p className="mt-2 text-right text-[10px] text-muted">
              {selected.candleCount.toLocaleString("en-US")} candles · {day(selected.fromTime)} →{" "}
              {day(selected.toTime)} · run {day(selected.createdAt)}
            </p>
          </Card>

          <Card title="Trades">
            {currentTrades === null ? (
              <p className="py-4 text-center text-xs text-muted">Loading…</p>
            ) : currentTrades.length === 0 ? (
              <p className="py-4 text-center text-xs text-muted">No trades in this run.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-[10px] uppercase tracking-wider text-muted">
                      <th className="py-1 pr-2">#</th>
                      <th className="py-1 pr-2">Time</th>
                      <th className="py-1 pr-2">Side</th>
                      <th className="py-1 pr-2">Entry</th>
                      <th className="py-1 pr-2">Stop</th>
                      <th className="py-1 pr-2">Target</th>
                      <th className="py-1 pr-2">Outcome</th>
                      <th className="py-1 pr-2">R</th>
                      <th className="py-1">Bars</th>
                    </tr>
                  </thead>
                  <tbody>
                    {currentTrades.slice(0, 100).map((t) => (
                      <tr key={t.seq} className="border-t border-border">
                        <td className="tnum py-1 pr-2 text-muted">{t.seq}</td>
                        <td className="tnum py-1 pr-2">{t.signalTime.slice(0, 16).replace("T", " ")}</td>
                        <td className={`py-1 pr-2 ${t.side === "buy" ? "text-profit" : "text-loss"}`}>
                          {t.side.toUpperCase()}
                        </td>
                        <td className="tnum py-1 pr-2">{t.entryPrice}</td>
                        <td className="tnum py-1 pr-2">{t.stopLoss}</td>
                        <td className="tnum py-1 pr-2">{t.takeProfit}</td>
                        <td className="py-1 pr-2">
                          <StatusPill tone={OUTCOME_TONES[t.outcome] ?? "muted"}>
                            {t.outcome}
                            {t.bothTouch ? " (both)" : ""}
                          </StatusPill>
                        </td>
                        <td
                          className={`tnum py-1 pr-2 ${t.rMultiple >= 0 ? "text-profit" : "text-loss"}`}
                        >
                          {t.rMultiple >= 0 ? "+" : ""}
                          {t.rMultiple}
                        </td>
                        <td className="tnum py-1">{t.barsHeld}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {currentTrades.length > 100 && (
                  <p className="mt-1 text-right text-[10px] text-muted">
                    Showing 100 of {currentTrades.length} trades.
                  </p>
                )}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
