/**
 * Shared enums for the trading cockpit.
 * Conceptual source of truth: context/realtime/event_contracts.md and
 * context/realtime/dashboard_realtime_model.md. Phase 02 will formalize these
 * into cross-platform (TS/.NET/MQL5) schemas.
 */

export type Environment = "mock" | "paper" | "demo" | "live";

export type ConnectionState =
  | "mock"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "stale"
  | "degraded"
  | "disconnected"
  | "error";

export type Side = "buy" | "sell";

export type Bias = "bullish" | "bearish" | "neutral";

export type RiskState = "normal" | "warning" | "locked";

export type SignalStatus =
  | "detected"
  | "scored"
  | "risk_review"
  | "approved"
  | "rejected"
  | "commanded"
  | "acknowledged"
  | "reported"
  | "expired";

export type AgentState = "connected" | "degraded" | "disconnected";

export type ExecutionReportStatus =
  | "acknowledged"
  | "submitted"
  | "filled"
  | "partially_filled"
  | "failed"
  | "position_opened"
  | "position_modified"
  | "position_closed";

export type TradingSession =
  | "asia"
  | "london"
  | "new_york_am"
  | "new_york_pm"
  | "off_session";
