/**
 * Domain primitives: identifiers and base vocabulary shared by every model.
 *
 * Portability rules (see context/domain/domain_model_mvp.md):
 * - plain interfaces and string-literal unions only, no classes or Date
 * - absent values are explicit `null`, never omitted/undefined
 * - timestamps are ISO 8601 UTC strings; numbers are IEEE doubles
 * These schemas are the canonical source later mirrored to .NET SignalR
 * contracts and MQL5 WebSocket message structs.
 */

/** ISO 8601 UTC timestamp, e.g. "2026-07-07T12:00:00.000Z". */
export type UtcTimestamp = string;

/** Broker symbol code, e.g. "XAUUSD". */
export type SymbolCode = string;

export type AccountId = string;
export type AgentId = string;
export type OrderId = string;
export type PositionId = string;
export type TradeId = string;
export type SignalId = string;
export type CommandId = string;
export type StrategyId = string;
export type RiskApprovalId = string;

/** Chart timeframe in platform-neutral notation. */
export type Timeframe =
  | "M1"
  | "M3"
  | "M5"
  | "M15"
  | "M30"
  | "H1"
  | "H4"
  | "D1"
  | "W1";

export type Side = "buy" | "sell";

export type Bias = "bullish" | "bearish" | "neutral";

/** ICT-style session buckets used for session gating and attribution. */
export type TradingSession =
  | "asia"
  | "london"
  | "new_york_am"
  | "new_york_pm"
  | "off_session";
