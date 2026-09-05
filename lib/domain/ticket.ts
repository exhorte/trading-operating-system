/**
 * Pre-trade ticket vocabulary (T04): the four buttons a trader presses
 * before placing a trade, captured at the moment of decision so the "why"
 * is never reconstructed after the fact. Symbol is a plain SymbolCode, not
 * hardcoded to XAUUSD — the UI defaults it, the domain stays general since
 * the table already carries a symbol column.
 */

import type { AccountId, SymbolCode, UtcTimestamp } from "./primitives";

export type SetupType = "fvg" | "order_block" | "liquidity_sweep" | "retest" | "other";

export type TradeBias = "long" | "short" | "contre_tendance";

export type Confidence = 1 | 2 | 3 | 4 | 5;

/**
 * What the ticket captures at creation. `matchedPositionId`/`matchedTradeId`
 * are deliberately NOT here: no execution-command pipeline produces a real
 * fill for a manual trade, so there is nothing to attach at creation time —
 * that reconciliation is T06's job, against the persisted row, later.
 */
export interface PreTradeTicket {
  ticketId: string;
  accountId: AccountId;
  symbol: SymbolCode;
  setup: SetupType;
  bias: TradeBias;
  entryPrice: number;
  stopLoss: number;
  /** Price that proves the trade wrong; defaults to stopLoss, editable. */
  invalidation: number;
  confidence: Confidence;
  /** Null when no take-profit was set at decision time — never reconstructed later. */
  takeProfit: number | null;
  /** Volume the sizing panel (T01) recommended at decision time (post 0.01-lot floor). */
  targetVolume: number | null;
  /** Dollar risk the policy targeted for this trade (T01's "risque visé"). */
  targetRiskUsd: number | null;
  createdAt: UtcTimestamp;
}
