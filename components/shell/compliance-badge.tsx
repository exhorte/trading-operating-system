"use client";

import { useEffect, useMemo, useState } from "react";
import { useCockpit } from "@/lib/realtime/provider";
import { backendHttpBase } from "@/lib/realtime/backend-url";
import { evaluateTrade, complianceRate, type ComplianceTradeInput } from "@/lib/compliance/evaluate";
import type { LockoutWindow } from "@/lib/compliance/violations";
import { defaultRiskPolicy } from "@/lib/risk/policy";
import { toCanonicalSymbol } from "@/lib/market/symbols/registry";
import { DEFAULT_SESSION_WINDOWS } from "@/lib/analysis/config";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";

const LOOKBACK_DAYS = 7;

/** Minimal slice of GET /api/journal/trades this badge needs. */
interface JournalTradeLite {
  brokerPositionId: string;
  symbol: string;
  openedAt: string | null;
  volume: number;
  entryPrice: number | null;
  stopLoss: number | null;
}

/**
 * T07 — the single weekly compliance curve, in the top bar where the P&L
 * would otherwise sit (charter.md, principe 2: the KPI is compliance, not
 * P&L on a noisy sample). Always a fixed trailing 7 days, independent of
 * whatever range /journal's own filter happens to show right now — same
 * detectors (lib/compliance/), a separate, smaller fetch.
 */
export function ComplianceBadge() {
  const { account } = useCockpit();
  const accountId = account?.accountId ?? null;
  const balance = account?.balance ?? null;

  const [trades, setTrades] = useState<JournalTradeLite[] | null>(null);
  const [lockouts, setLockouts] = useState<LockoutWindow[]>([]);

  useEffect(() => {
    if (!accountId) {
      return;
    }
    let cancelled = false;

    async function load() {
      const base = backendHttpBase();
      const to = new Date();
      const from = new Date(to.getTime() - LOOKBACK_DAYS * 24 * 60 * 60 * 1000);
      try {
        const [tradesRes, lockoutsRes] = await Promise.all([
          fetch(
            `${base}/api/journal/trades?accountId=${encodeURIComponent(accountId!)}` +
              `&from=${from.toISOString().slice(0, 10)}&to=${to.toISOString().slice(0, 10)}`,
          ),
          fetch(
            `${base}/api/risk/lockouts?accountId=${encodeURIComponent(accountId!)}` +
              `&to=${encodeURIComponent(to.toISOString())}`,
          ),
        ]);
        if (cancelled) {
          return;
        }
        setTrades(tradesRes.ok ? ((await tradesRes.json()) as JournalTradeLite[]) : []);
        setLockouts(lockoutsRes.ok ? ((await lockoutsRes.json()) as LockoutWindow[]) : []);
      } catch {
        if (!cancelled) {
          setTrades(null);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [accountId]);

  const rate = useMemo(() => {
    if (!accountId || !trades) {
      return null;
    }
    const policy = defaultRiskPolicy(accountId);
    const violationsPerTrade = trades.map((t) => {
      const input: ComplianceTradeInput = {
        brokerPositionId: t.brokerPositionId,
        symbol: toCanonicalSymbol(t.symbol),
        openedAt: t.openedAt,
        volume: t.volume,
        entryPrice: t.entryPrice,
        stopLoss: t.stopLoss,
      };
      return evaluateTrade(input, lockouts, DEFAULT_SESSION_WINDOWS, balance, policy);
    });
    return complianceRate(violationsPerTrade);
  }, [accountId, trades, lockouts, balance]);

  if (!accountId || rate === null) {
    return <StatusPill tone="muted">Conformité —</StatusPill>;
  }

  const percent = Math.round(rate * 100);
  const tone: PillTone = rate >= 0.9 ? "profit" : rate >= 0.7 ? "warning" : "loss";
  return (
    <StatusPill tone={tone} pulse={rate < 0.7}>
      {percent}% conformité (7j)
    </StatusPill>
  );
}
