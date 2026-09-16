"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useCockpit } from "@/lib/realtime/provider";
import { backendHttpBase } from "@/lib/realtime/backend-url";
import { formatPrice, formatSignedMoney } from "@/lib/format";
import { sessionForTimestamp } from "@/lib/analysis/sessions";
import { DEFAULT_SESSION_WINDOWS } from "@/lib/analysis/config";
import { reconcile, type ReconciliationTrade } from "@/lib/setup/reconciliation";
import { evaluateTrade, type ComplianceTradeInput } from "@/lib/compliance/evaluate";
import type { LockoutWindow, Violation } from "@/lib/compliance/violations";
import { defaultRiskPolicy } from "@/lib/risk/policy";
import { toCanonicalSymbol } from "@/lib/market/symbols/registry";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import type { Side } from "@/lib/domain/primitives";

/** Shape of one row from GET /api/journal/trades (JournalRepository.GetTradesAsync). */
interface JournalTrade {
  brokerPositionId: string;
  symbol: string;
  side: string;
  volume: number;
  entryPrice: number | null;
  exitPrice: number;
  realizedPnl: number;
  stopLoss: number | null;
  openedAt: string | null;
  closedAt: string;
  hasCapture: boolean;
}

/** Shape of one row from GET /api/setup-proposals (SetupProposalRepository.GetRecentAsync). */
interface SetupProposal {
  symbol: string;
  eventAt: string;
  status: "proposed" | "blocked";
  side: Side | null;
  sweptLevelKind: string | null;
  costRatio: number | null;
  riskRewardRatio: number | null;
}

/** Same tolerance and rationale as reconciliation-view.tsx's own constant
 *  (not exported from there — re-stated here, kept in sync deliberately,
 *  not coincidentally): "un trade pris trois minutes après une proposition
 *  sur le même niveau est le même trade" (EA-02 prompt). */
const PROPOSAL_TOLERANCE_MINUTES = 5;

const inputClass = "rounded border border-border bg-surface-elevated px-2 py-1 text-xs text-foreground";

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function defaultFrom(): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - 90);
  return isoDate(d);
}

/**
 * R multiple — same formula as the live one in mt5-translate.ts::toPosition
 * (move / risk, direction-adjusted), reimplemented rather than imported: that
 * one takes a live currentPrice, this one a fixed exitPrice, and it returns
 * null (not 0) when there's no denominator — entryPrice/stopLoss only exist
 * via a T05 capture (T06 fiche, Décision 3), so "no capture" and "no stop
 * set" must read as unknown, not as a flat breakeven.
 */
function computeRMultiple(trade: JournalTrade): number | null {
  if (trade.entryPrice === null || trade.stopLoss === null || trade.stopLoss <= 0) {
    return null;
  }
  const direction = trade.side === "buy" ? 1 : -1;
  const move = (trade.exitPrice - trade.entryPrice) * direction;
  const risk = Math.abs(trade.entryPrice - trade.stopLoss);
  return risk > 0 ? Math.round((move / risk) * 100) / 100 : null;
}

function formatDuration(openedAt: string | null, closedAt: string): string {
  if (!openedAt) {
    return "—";
  }
  const ms = new Date(closedAt).getTime() - new Date(openedAt).getTime();
  if (ms < 0) {
    return "—";
  }
  const totalSeconds = Math.round(ms / 1000);
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (h > 0) {
    return `${h}h${m}m`;
  }
  if (m > 0) {
    return `${m}m${s}s`;
  }
  return `${s}s`;
}

interface Bucket {
  label: string;
  trades: number;
  pnl: number;
}

/** Aggregates by a key derived per-trade; buckets with no key (e.g. no
 *  openedAt) are dropped rather than pooled under a fake "unknown" bucket
 *  the pnl total would otherwise silently absorb. */
function bucketBy(trades: JournalTrade[], keyOf: (t: JournalTrade) => string | null): Bucket[] {
  const byLabel = new Map<string, Bucket>();
  for (const t of trades) {
    const label = keyOf(t);
    if (label === null) {
      continue;
    }
    const existing = byLabel.get(label);
    if (existing) {
      existing.trades += 1;
      existing.pnl += t.realizedPnl;
    } else {
      byLabel.set(label, { label, trades: 1, pnl: t.realizedPnl });
    }
  }
  return Array.from(byLabel.values());
}

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function BreakdownTable({ title, buckets }: { title: string; buckets: Bucket[] }) {
  return (
    <Card title={title}>
      {buckets.length === 0 ? (
        <p className="text-xs text-muted">No data.</p>
      ) : (
        <table className="w-full text-xs">
          <tbody>
            {buckets.map((b) => (
              <tr key={b.label} className="border-b border-border/50 last:border-0">
                <td className="py-1 pr-3">{b.label}</td>
                <td className="tnum py-1 pr-3 text-muted">{b.trades}</td>
                <td className={`tnum py-1 text-right font-medium ${b.pnl >= 0 ? "text-profit" : "text-loss"}`}>
                  {formatSignedMoney(b.pnl)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

/** One month's P&L calendar grid — Sun-Sat columns, padded to full weeks. */
function MonthCalendar({ year, month, dayTotals }: { year: number; month: number; dayTotals: Map<string, Bucket> }) {
  const firstWeekday = new Date(Date.UTC(year, month, 1)).getUTCDay();
  const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const cells: Array<{ day: number; key: string } | null> = [];
  for (let i = 0; i < firstWeekday; i++) {
    cells.push(null);
  }
  for (let day = 1; day <= daysInMonth; day++) {
    const key = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    cells.push({ day, key });
  }
  while (cells.length % 7 !== 0) {
    cells.push(null);
  }

  const monthLabel = new Date(Date.UTC(year, month, 1)).toLocaleDateString("en-US", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });

  return (
    <Card title={monthLabel}>
      <div className="grid grid-cols-7 gap-1 text-center text-[10px]">
        {WEEKDAY_LABELS.map((w) => (
          <div key={w} className="pb-1 font-medium uppercase tracking-wider text-muted">
            {w}
          </div>
        ))}
        {cells.map((cell, i) => {
          if (!cell) {
            return <div key={`pad-${i}`} />;
          }
          const bucket = dayTotals.get(cell.key);
          return (
            <div
              key={cell.key}
              className={`flex flex-col items-center gap-0.5 rounded border border-border p-1 ${
                bucket ? (bucket.pnl >= 0 ? "bg-profit/10" : "bg-loss/10") : ""
              }`}
            >
              <span className="text-muted">{cell.day}</span>
              {bucket && (
                <span className={`tnum font-medium ${bucket.pnl >= 0 ? "text-profit" : "text-loss"}`}>
                  {formatSignedMoney(bucket.pnl)}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

/**
 * T06 — browsable, filterable trade journal. Zero manual entry: every row
 * comes from closed_trades/position_opens/trade_captures via
 * GET /api/journal/trades (JournalRepository). No new table — see the
 * fiche's Décision 2. Per-trade realized P&L shown as a fact (same as the
 * live uP&L already on positions-table.tsx); no aggregate performance
 * metric (expectancy/profit factor/equity curve) — Décision 1.
 */
export default function TradesJournalPage() {
  const { account } = useCockpit();
  const accountId = account?.accountId ?? null;

  const [from, setFrom] = useState(defaultFrom());
  const [to, setTo] = useState(isoDate(new Date()));
  const [symbol, setSymbol] = useState<string>("all");
  const [trades, setTrades] = useState<JournalTrade[] | null>(null);
  const [proposals, setProposals] = useState<SetupProposal[] | null>(null);
  const [lockouts, setLockouts] = useState<LockoutWindow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!accountId) {
      return;
    }
    let cancelled = false;

    async function load() {
      try {
        const base = backendHttpBase();
        const [tradesRes, proposalsRes, lockoutsRes] = await Promise.all([
          fetch(
            `${base}/api/journal/trades?accountId=${encodeURIComponent(accountId!)}` +
              `&from=${from}&to=${to}`,
          ),
          // EA-02 context, best-effort enrichment (fiche Décision — coïncidence,
          // jamais le pourquoi) — its own fetch failing must not break the journal.
          fetch(`${base}/api/setup-proposals?since=${encodeURIComponent(new Date(from).toISOString())}`),
          // T07 — lockout windows up to `to`, for detectLockoutViolation.
          // Best-effort too: a failed fetch degrades to "no violations
          // detected", not to a broken journal.
          fetch(
            `${base}/api/risk/lockouts?accountId=${encodeURIComponent(accountId!)}` +
              `&to=${encodeURIComponent(new Date(to).toISOString())}`,
          ),
        ]);
        if (!tradesRes.ok) {
          throw new Error("journal fetch failed");
        }
        const body = (await tradesRes.json()) as JournalTrade[];
        const proposalBody = proposalsRes.ok ? ((await proposalsRes.json()) as SetupProposal[]) : [];
        const lockoutBody = lockoutsRes.ok ? ((await lockoutsRes.json()) as LockoutWindow[]) : [];
        if (!cancelled) {
          setTrades(body);
          setProposals(proposalBody);
          setLockouts(lockoutBody);
          setError(null);
        }
      } catch {
        if (!cancelled) {
          setError("Could not load the trade journal.");
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [accountId, from, to]);

  const symbols = useMemo(
    () => Array.from(new Set((trades ?? []).map((t) => t.symbol))).sort(),
    [trades],
  );

  const filtered = useMemo(
    () => (trades ?? []).filter((t) => symbol === "all" || t.symbol === symbol),
    [trades, symbol],
  );

  /** brokerPositionId -> the proposal it coincided with, when EA-02 detected
   *  one within tolerance. Approximation of context, never the user's own
   *  "why" — T04 (the pre-trade ticket that captured that) was retired. */
  const proposalByTrade = useMemo(() => {
    const map = new Map<string, SetupProposal>();
    if (!proposals) {
      return map;
    }
    const reconcilable: ReconciliationTrade[] = filtered
      .filter((t): t is JournalTrade & { openedAt: string } => t.openedAt !== null)
      .map((t) => ({ brokerPositionId: t.brokerPositionId, symbol: t.symbol, side: t.side as Side, openedAt: t.openedAt }));
    const eligible = proposals.filter(
      (p): p is SetupProposal & { side: Side } => p.status === "proposed" && p.side !== null,
    );
    const rows = reconcile(
      eligible.map((p) => ({ symbol: p.symbol, side: p.side, detectedAt: p.eventAt })),
      reconcilable,
      PROPOSAL_TOLERANCE_MINUTES,
    );
    for (const row of rows) {
      if (row.class !== "PROPOSE_ET_PRIS" || !row.brokerPositionId || !row.proposalDetectedAt) {
        continue;
      }
      const proposal = eligible.find((p) => p.symbol === row.symbol && p.eventAt === row.proposalDetectedAt);
      if (proposal) {
        map.set(row.brokerPositionId, proposal);
      }
    }
    return map;
  }, [filtered, proposals]);

  /** brokerPositionId -> violations (T07). Lockout/session are always
   *  judged when openedAt is known; size only when a balance is available
   *  (fiche Décision 2: current balance, an approximation of balance at
   *  trade time — no historical account.snapshot table exists yet). */
  const violationsByTrade = useMemo(() => {
    const map = new Map<string, Violation[]>();
    if (!accountId) {
      return map;
    }
    const policy = defaultRiskPolicy(accountId);
    const balance = account?.balance ?? null;
    for (const t of filtered) {
      const input: ComplianceTradeInput = {
        brokerPositionId: t.brokerPositionId,
        symbol: toCanonicalSymbol(t.symbol),
        openedAt: t.openedAt,
        volume: t.volume,
        entryPrice: t.entryPrice,
        stopLoss: t.stopLoss,
      };
      map.set(t.brokerPositionId, evaluateTrade(input, lockouts, DEFAULT_SESSION_WINDOWS, balance, policy));
    }
    return map;
  }, [filtered, lockouts, accountId, account?.balance]);

  const dayTotals = useMemo(() => {
    const map = new Map<string, Bucket>();
    for (const t of filtered) {
      const key = t.closedAt.slice(0, 10);
      const existing = map.get(key);
      if (existing) {
        existing.trades += 1;
        existing.pnl += t.realizedPnl;
      } else {
        map.set(key, { label: key, trades: 1, pnl: t.realizedPnl });
      }
    }
    return map;
  }, [filtered]);

  const months = useMemo(() => {
    const seen = new Map<string, { year: number; month: number }>();
    for (const t of filtered) {
      const d = new Date(t.closedAt);
      const key = `${d.getUTCFullYear()}-${d.getUTCMonth()}`;
      if (!seen.has(key)) {
        seen.set(key, { year: d.getUTCFullYear(), month: d.getUTCMonth() });
      }
    }
    return Array.from(seen.values()).sort((a, b) => a.year - b.year || a.month - b.month);
  }, [filtered]);

  const bySymbol = useMemo(() => bucketBy(filtered, (t) => t.symbol), [filtered]);
  const bySession = useMemo(
    () =>
      bucketBy(filtered, (t) =>
        t.openedAt ? sessionForTimestamp(t.openedAt, DEFAULT_SESSION_WINDOWS) : null,
      ),
    [filtered],
  );
  const byWeekday = useMemo(
    () =>
      bucketBy(filtered, (t) => (t.openedAt ? WEEKDAY_LABELS[new Date(t.openedAt).getUTCDay()] : null)).sort(
        (a, b) => WEEKDAY_LABELS.indexOf(a.label) - WEEKDAY_LABELS.indexOf(b.label),
      ),
    [filtered],
  );
  const byHour = useMemo(
    () =>
      bucketBy(filtered, (t) =>
        t.openedAt ? String(new Date(t.openedAt).getUTCHours()).padStart(2, "0") + "h UTC" : null,
      ).sort((a, b) => a.label.localeCompare(b.label)),
    [filtered],
  );

  if (!accountId) {
    return (
      <Card title="Trades journal">
        <Skeleton className="h-72" />
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <Card title="Filters">
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <label className="flex items-center gap-1.5 text-muted">
            From
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className={inputClass} />
          </label>
          <label className="flex items-center gap-1.5 text-muted">
            To
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className={inputClass} />
          </label>
          <label className="flex items-center gap-1.5 text-muted">
            Symbol
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)} className={inputClass}>
              <option value="all">All</option>
              {symbols.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        </div>
      </Card>

      {error ? (
        <EmptyState title="No journal data" description={error} hint="T06" />
      ) : !trades ? (
        <Card title="Trades">
          <Skeleton className="h-72" />
        </Card>
      ) : filtered.length === 0 ? (
        <EmptyState
          title="No closed trades in this range"
          description="Widen the date range, or clear the symbol filter."
          hint="T06 — zero manual entry: rows appear automatically as trades close"
        />
      ) : (
        <Card title={`Trades (${filtered.length})`}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-xs">
              <thead>
                <tr className="border-b border-border text-left text-[10px] uppercase tracking-wider text-muted">
                  {["Closed", "Symbol", "Side", "Volume", "Entry", "Exit", "R", "P&L", "Duration", "Setup", "Violations", ""].map(
                    (header) => (
                      <th key={header} className="pb-1.5 pr-3 font-medium">
                        {header}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {filtered.map((t) => {
                  const r = computeRMultiple(t);
                  return (
                    <tr key={t.brokerPositionId} className="border-b border-border/50 last:border-0">
                      <td className="py-1.5 pr-3 text-muted">{new Date(t.closedAt).toLocaleString()}</td>
                      <td className="py-1.5 pr-3 font-medium">{t.symbol}</td>
                      <td
                        className={`py-1.5 pr-3 font-medium ${t.side === "buy" ? "text-profit" : "text-loss"}`}
                      >
                        {t.side.toUpperCase()}
                      </td>
                      <td className="tnum py-1.5 pr-3">{t.volume.toFixed(2)}</td>
                      <td className="tnum py-1.5 pr-3">{t.entryPrice !== null ? formatPrice(t.entryPrice) : "—"}</td>
                      <td className="tnum py-1.5 pr-3">{formatPrice(t.exitPrice)}</td>
                      <td className={`tnum py-1.5 pr-3 ${r === null ? "text-muted" : r >= 0 ? "text-profit" : "text-loss"}`}>
                        {r === null ? "—" : r.toFixed(2)}
                      </td>
                      <td
                        className={`tnum py-1.5 pr-3 font-medium ${t.realizedPnl >= 0 ? "text-profit" : "text-loss"}`}
                      >
                        {formatSignedMoney(t.realizedPnl)}
                      </td>
                      <td className="py-1.5 pr-3 text-muted">{formatDuration(t.openedAt, t.closedAt)}</td>
                      <td className="py-1.5 pr-3">
                        {(() => {
                          const p = proposalByTrade.get(t.brokerPositionId);
                          if (!p) {
                            return <span className="text-muted">—</span>;
                          }
                          const detail = [
                            p.sweptLevelKind,
                            p.costRatio !== null ? `cost ${p.costRatio.toFixed(2)}` : null,
                            p.riskRewardRatio !== null ? `R:R ${p.riskRewardRatio.toFixed(2)}` : null,
                          ]
                            .filter(Boolean)
                            .join(" · ");
                          return (
                            <span className="text-info" title={detail || "EA-02 proposal coincided"}>
                              S01
                            </span>
                          );
                        })()}
                      </td>
                      <td className="py-1.5 pr-3">
                        {(() => {
                          const violations = violationsByTrade.get(t.brokerPositionId) ?? [];
                          if (violations.length === 0) {
                            return <span className="text-muted">—</span>;
                          }
                          return (
                            <span
                              className="text-loss"
                              title={violations.map((v) => v.detail).join(" · ")}
                            >
                              {violations.map((v) => v.type).join(", ")}
                            </span>
                          );
                        })()}
                      </td>
                      <td className="py-1.5">
                        {t.hasCapture ? (
                          <Link href={`/journal/${t.brokerPositionId}`} className="text-info hover:underline">
                            Capture
                          </Link>
                        ) : (
                          <span className="text-muted">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {filtered.length > 0 && (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {months.map(({ year, month }) => (
              <MonthCalendar key={`${year}-${month}`} year={year} month={month} dayTotals={dayTotals} />
            ))}
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
            <BreakdownTable title="By symbol" buckets={bySymbol} />
            <BreakdownTable title="By session" buckets={bySession} />
            <BreakdownTable title="By weekday" buckets={byWeekday} />
            <BreakdownTable title="By entry hour" buckets={byHour} />
          </div>
        </>
      )}
    </div>
  );
}
