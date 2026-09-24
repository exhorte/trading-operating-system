"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { analyzeMarketContext } from "@/lib/analysis";
import { aggregateCandles } from "@/lib/analysis/aggregate";
import { useCockpit } from "@/lib/realtime/provider";
import { backendHttpBase } from "@/lib/realtime/backend-url";
import { TradeChart, type TradeChartMarker } from "@/components/journal/trade-chart";
import { Panel } from "@/components/ui/panel";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import type { Candle } from "@/lib/domain/market";
import type { Timeframe } from "@/lib/domain/primitives";
import type { MarketContextState } from "@/lib/domain/analysis";

/** Shape of GET /api/captures/:id (TradeCaptureRepository.TradeCaptureFact). */
interface CaptureFact {
  symbol: string;
  timeframe: string;
  windowStartUtc: string;
  windowEndUtc: string;
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
  exitPrice: number | null;
}

interface CaptureSection {
  title: string;
  candles: Candle[];
  context: MarketContextState | null;
  markers: TradeChartMarker[];
}

async function fetchCandles(
  base: string,
  symbol: string,
  timeframe: string,
  fromUtc: string,
  toUtc: string,
): Promise<Candle[]> {
  const res = await fetch(
    `${base}/api/candles?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}` +
      `&from=${encodeURIComponent(fromUtc)}&to=${encodeURIComponent(toUtc)}`,
  );
  return res.ok ? ((await res.json()) as Candle[]) : [];
}

/**
 * The capture's declared timeframe is whatever the general observer was
 * streaming when the fact was written (XAUUSDm M15 today) — it is NOT a
 * promise that this symbol has candles stored at that timeframe. Only
 * XAUUSDm has M15; EURUSDm/GBPUSDm only have M1, written by EA-02's worker.
 * So: ask for the declared timeframe, and when the store has nothing there,
 * rebuild it from M1 with the same aggregation EA-02 uses
 * (lib/analysis/aggregate.ts — pure, tested, and the canonical engine per
 * ADR 0004, which is also why this fallback lives here in TypeScript rather
 * than in the C# /api/candles endpoint).
 */
async function loadCaptureCandles(base: string, fact: CaptureFact): Promise<Candle[]> {
  const declared = await fetchCandles(
    base,
    fact.symbol,
    fact.timeframe,
    fact.windowStartUtc,
    fact.windowEndUtc,
  );
  if (declared.length > 0 || fact.timeframe === "M1") {
    return declared;
  }
  const m1 = await fetchCandles(base, fact.symbol, "M1", fact.windowStartUtc, fact.windowEndUtc);
  if (m1.length === 0) {
    return [];
  }
  return aggregateCandles(m1, "M1", fact.timeframe as Timeframe);
}

/**
 * MT5 reports 0 for a stop-loss / take-profit that was never attached — it is
 * "unset", not "a level at zero". Drawing it as a line would be a lie about
 * the trade, and worse, it drags computePriceScale's range down to zero and
 * flattens every real candle into a one-pixel band (seen for real on position
 * 3230177984, 2026-09-15). An absent line reads correctly as "no stop was set".
 */
function buildMarkers(fact: CaptureFact): TradeChartMarker[] {
  const markers: TradeChartMarker[] = [{ price: fact.entryPrice, label: "Entry", tone: "entry" }];
  if (fact.stopLoss > 0) {
    markers.push({ price: fact.stopLoss, label: "SL", tone: "stop" });
  }
  if (fact.takeProfit > 0) {
    markers.push({ price: fact.takeProfit, label: "TP", tone: "target" });
  }
  if (fact.exitPrice !== null) {
    markers.push({ price: fact.exitPrice, label: "Exit", tone: "exit" });
  }
  return markers;
}

/**
 * T05 — minimal deep-link viewer for one trade's captures. Deliberately NOT
 * the browsable journal (dense table, filters, tags) — that is T06's scope
 * (see the /journal stub page). This proves the pipeline end to end: fetch
 * the immutable facts, fetch candles within their frozen window, run
 * analyzeMarketContext (the canonical engine, ADR 0004) client-side, render.
 */
export default function TradeCapturePage() {
  const params = useParams<{ brokerPositionId: string }>();
  const { account } = useCockpit();
  const accountId = account?.accountId ?? null;

  const [sections, setSections] = useState<CaptureSection[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!accountId) {
      return;
    }
    let cancelled = false;

    async function load() {
      try {
        const base = backendHttpBase();
        const capturesRes = await fetch(
          `${base}/api/captures/${params.brokerPositionId}?accountId=${encodeURIComponent(accountId!)}`,
        );
        if (!capturesRes.ok) {
          throw new Error("captures fetch failed");
        }
        const { entry, exit } = (await capturesRes.json()) as {
          entry: CaptureFact | null;
          exit: CaptureFact | null;
        };
        if (!entry) {
          if (!cancelled) {
            setError("No capture recorded for this trade — either it predates T05, or the entry hasn't been observed yet.");
          }
          return;
        }

        const facts: Array<{ title: string; fact: CaptureFact }> = [{ title: "Entry", fact: entry }];
        if (exit) {
          facts.push({ title: "Exit", fact: exit });
        }

        const built: CaptureSection[] = [];
        for (const { title, fact } of facts) {
          const rows = await loadCaptureCandles(base, fact);
          const context =
            rows.length > 0
              ? analyzeMarketContext({
                  symbol: fact.symbol,
                  timeframe: fact.timeframe as Candle["timeframe"],
                  candles: rows,
                })
              : null;
          built.push({ title, candles: rows, context, markers: buildMarkers(fact) });
        }
        if (!cancelled) {
          setSections(built);
        }
      } catch {
        if (!cancelled) {
          setError("Could not load this trade's capture.");
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [params.brokerPositionId, accountId]);

  if (!accountId) {
    return (
      <Panel title="Trade capture">
        <Skeleton className="h-72" />
      </Panel>
    );
  }

  if (error) {
    return <EmptyState title="No capture" description={error} hint={`Position ${params.brokerPositionId}`} />;
  }

  if (!sections) {
    return (
      <Panel title="Trade capture">
        <Skeleton className="h-72" />
      </Panel>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {sections.map((section) => (
        <Panel key={section.title} title={`${section.title} — position ${params.brokerPositionId}`}>
          <TradeChart candles={section.candles} context={section.context} markers={section.markers} />
        </Panel>
      ))}
    </div>
  );
}
