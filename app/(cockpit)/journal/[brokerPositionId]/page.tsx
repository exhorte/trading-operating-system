"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, Camera } from "lucide-react";
import { analyzeMarketContext } from "@/lib/analysis";
import { aggregateCandles } from "@/lib/analysis/aggregate";
import { useCockpit } from "@/lib/realtime/provider";
import { backendHttpBase } from "@/lib/realtime/backend-url";
import { CaptureMetrics, type CaptureLevels } from "@/components/journal/capture-metrics";
import { type TradeChartMarker } from "@/components/journal/trade-chart";
import { TradeChartFrame } from "@/components/journal/trade-chart-frame";
import { PageHeader } from "@/components/shell/page-header";
import { Button } from "@/components/ui/button";
import { Callout } from "@/components/ui/callout";
import { EmptyState } from "@/components/ui/empty-state";
import { Panel } from "@/components/ui/panel";
import { Skeleton } from "@/components/ui/skeleton";
import { SplitLayout } from "@/components/ui/split-layout";
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
  title: "Entry" | "Exit";
  symbol: string;
  timeframe: string;
  candles: Candle[];
  context: MarketContextState | null;
  markers: TradeChartMarker[];
}

/** What the section titles are called on screen; the keys above stay the data's own. */
const SECTION_LABELS: Record<CaptureSection["title"], string> = { Entry: "Entrée", Exit: "Sortie" };

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
  const markers: TradeChartMarker[] = [{ price: fact.entryPrice, label: "Entrée", tone: "entry" }];
  if (fact.stopLoss > 0) {
    markers.push({ price: fact.stopLoss, label: "SL", tone: "stop" });
  }
  if (fact.takeProfit > 0) {
    markers.push({ price: fact.takeProfit, label: "TP", tone: "target" });
  }
  if (fact.exitPrice !== null) {
    markers.push({ price: fact.exitPrice, label: "Sortie", tone: "exit" });
  }
  return markers;
}

/** The levels of the dark panel, read back from the markers the chart draws — one source for both. */
function levelsOf(sections: CaptureSection[]): CaptureLevels | null {
  const entry = sections.find((section) => section.title === "Entry");
  if (!entry) {
    return null;
  }
  const priceOf = (section: CaptureSection | undefined, tone: TradeChartMarker["tone"]) =>
    section?.markers.find((marker) => marker.tone === tone)?.price ?? null;
  const exit = sections.find((section) => section.title === "Exit");
  return {
    symbol: entry.symbol,
    timeframe: entry.timeframe,
    entry: priceOf(entry, "entry"),
    stop: priceOf(entry, "stop"),
    target: priceOf(entry, "target"),
    exit: priceOf(exit, "exit"),
  };
}

/**
 * T05 — minimal deep-link viewer for one trade's captures. Deliberately NOT
 * the browsable journal (dense table, filters, tags) — that is T06's scope
 * (see the /journal page). This proves the pipeline end to end: fetch
 * the immutable facts, fetch candles within their frozen window, run
 * analyzeMarketContext (the canonical engine, ADR 0004) client-side, render.
 *
 * Composition (ADR 0017): the charts on the left, the frozen levels in the
 * dark panel on the right (first on mobile). « No capture » is an empty state
 * — nothing was recorded — while a failed read is a warning: the two must not
 * look alike.
 */
export default function TradeCapturePage() {
  const params = useParams<{ brokerPositionId: string }>();
  const { account } = useCockpit();
  const accountId = account?.accountId ?? null;

  const [sections, setSections] = useState<CaptureSection[] | null>(null);
  const [missing, setMissing] = useState(false);
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
            setMissing(true);
          }
          return;
        }

        const facts: Array<{ title: CaptureSection["title"]; fact: CaptureFact }> = [{ title: "Entry", fact: entry }];
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
          built.push({
            title,
            symbol: fact.symbol,
            timeframe: fact.timeframe,
            candles: rows,
            context,
            markers: buildMarkers(fact),
          });
        }
        if (!cancelled) {
          setSections(built);
        }
      } catch {
        if (!cancelled) {
          setError("Impossible de charger la capture de ce trade.");
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [params.brokerPositionId, accountId]);

  const header = (
    <PageHeader
      title="Capture du trade"
      subtitle={`Position ${params.brokerPositionId}`}
      icon={Camera}
      actions={
        <Button asChild variant="outline" size="sm">
          <Link href="/journal">
            <ArrowLeft aria-hidden="true" />
            Retour au journal
          </Link>
        </Button>
      }
    />
  );

  if (!accountId || (!sections && !missing && !error)) {
    return (
      <div className="flex flex-col gap-10">
        <SplitLayout
          main={
            <>
              {header}
              <Skeleton className="h-96 rounded-xl" />
            </>
          }
          aside={
            <>
              <Skeleton className="h-[72px] rounded-xl" />
              <Skeleton className="h-[420px] rounded-xl" />
            </>
          }
        />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col gap-10">
        {header}
        <Callout title="Capture illisible" variant="warning">
          {error}{" "}
          Le backend répond-il ?
        </Callout>
      </div>
    );
  }

  if (missing || !sections) {
    return (
      <div className="flex flex-col gap-10">
        {header}
        <EmptyState
          icon={Camera}
          title="Aucune capture pour ce trade"
          description="Aucune capture n'a été enregistrée pour cette position : soit elle est antérieure à T05, soit son ouverture n'a pas encore été observée."
          hint={`Position ${params.brokerPositionId}`}
        />
      </div>
    );
  }

  const levels = levelsOf(sections);

  return (
    <div className="flex flex-col gap-10">
      <SplitLayout
        stickyAside
        asideFirstOnMobile
        main={
          <>
            {header}
            {sections.map((section) => (
              <Panel key={section.title} title={SECTION_LABELS[section.title]} description={`${section.symbol} · ${section.timeframe}`}>
                <TradeChartFrame candles={section.candles} context={section.context} markers={section.markers} />
              </Panel>
            ))}
          </>
        }
        aside={levels ? <CaptureMetrics levels={levels} /> : null}
      />
      <Callout title="Important">
        La capture est rendue à la demande à partir des faits enregistrés à l&apos;ouverture et à la clôture, avec les
        bougies de la fenêtre figée — jamais une image prise après coup. Une ligne de stop ou d&apos;objectif absente
        veut dire « non posé » : MT5 renvoie 0 pour un niveau qui n&apos;a jamais été attaché.
      </Callout>
    </div>
  );
}
