"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { analyzeMarketContext } from "@/lib/analysis";
import { useCockpit } from "@/lib/realtime/provider";
import { backendHttpBase } from "@/lib/realtime/backend-url";
import { TradeChart, type TradeChartMarker } from "@/components/journal/trade-chart";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import type { Candle } from "@/lib/domain/market";
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

function buildMarkers(fact: CaptureFact): TradeChartMarker[] {
  const markers: TradeChartMarker[] = [
    { price: fact.entryPrice, label: "Entry", tone: "entry" },
    { price: fact.stopLoss, label: "SL", tone: "stop" },
    { price: fact.takeProfit, label: "TP", tone: "target" },
  ];
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
          const candlesRes = await fetch(
            `${base}/api/candles?symbol=${encodeURIComponent(fact.symbol)}&timeframe=${encodeURIComponent(fact.timeframe)}` +
              `&from=${encodeURIComponent(fact.windowStartUtc)}&to=${encodeURIComponent(fact.windowEndUtc)}`,
          );
          const rows = candlesRes.ok ? ((await candlesRes.json()) as Candle[]) : [];
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
      <Card title="Trade capture">
        <Skeleton className="h-72" />
      </Card>
    );
  }

  if (error) {
    return <EmptyState title="No capture" description={error} hint={`Position ${params.brokerPositionId}`} />;
  }

  if (!sections) {
    return (
      <Card title="Trade capture">
        <Skeleton className="h-72" />
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {sections.map((section) => (
        <Card key={section.title} title={`${section.title} — position ${params.brokerPositionId}`}>
          <TradeChart candles={section.candles} context={section.context} markers={section.markers} />
        </Card>
      ))}
    </div>
  );
}
