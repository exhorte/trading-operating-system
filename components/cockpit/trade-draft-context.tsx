"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { SizingPanelResult } from "@/lib/risk/sizing-panel";

/**
 * The trade currently being sized in T01's panel — shared so T04's ticket
 * can prefill its invalidation from the live stop and record the sizing
 * panel's own volume/risk figures, instead of re-typing values already on
 * screen or reimplementing the sizing math a second time.
 */
export interface TradeDraft {
  entryPrice: number | null;
  stopLoss: number | null;
  takeProfit: number | null;
  /** Latest sizing computation for entryPrice/stopLoss/takeProfit, null until valid. */
  sizing: SizingPanelResult | null;
}

const EMPTY_DRAFT: TradeDraft = {
  entryPrice: null,
  stopLoss: null,
  takeProfit: null,
  sizing: null,
};

interface TradeDraftContextValue {
  draft: TradeDraft;
  setDraft: (draft: TradeDraft) => void;
}

const TradeDraftContext = createContext<TradeDraftContextValue | null>(null);

export function TradeDraftProvider({ children }: { children: ReactNode }) {
  const [draft, setDraft] = useState<TradeDraft>(EMPTY_DRAFT);
  const value = useMemo(() => ({ draft, setDraft }), [draft]);
  return <TradeDraftContext.Provider value={value}>{children}</TradeDraftContext.Provider>;
}

export function useTradeDraft(): TradeDraftContextValue {
  const ctx = useContext(TradeDraftContext);
  if (!ctx) {
    throw new Error("useTradeDraft must be used inside <TradeDraftProvider>");
  }
  return ctx;
}
