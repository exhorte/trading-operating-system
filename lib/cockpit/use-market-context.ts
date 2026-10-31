"use client";

import { useMemo } from "react";
import { useApi } from "@/lib/api/use-api";
import { useCockpit } from "@/lib/realtime/provider";
import { toMarketContextView, type MarketContextView } from "./market-context-view";

export interface MarketContextRead {
  /** The symbol the context is about — the first one the core watches for the active account. */
  symbol: string | null;
  /** Null until the first answer; the last answer is kept while a refresh is in flight or fails. */
  context: MarketContextView | null;
  error: Error | null;
}

/**
 * The ICT/SMC context of the watched symbol, as the core computes it at the last closed candle (context, never a signal —
 * ADR 0002). Read over HTTP, and read again whenever a bar closes: the stream says *that* one did, the analysis is the core's.
 */
export function useMarketContext(): MarketContextRead {
  const { activeAccountId, watchlist, account } = useCockpit();
  const symbol = watchlist[0] ?? null;
  // Only an account the core is reading can be analysed — asking earlier is a guaranteed refusal.
  const args = activeAccountId !== null && account !== null && symbol !== null
    ? { path: { symbol }, query: { accountId: activeAccountId } }
    : null;
  const { data, error } = useApi("market_context", args, { refreshOn: ["market.candle_closed"] });
  const context = useMemo(() => (data === null ? null : toMarketContextView(data)), [data]);
  return { symbol, context, error };
}
