/**
 * Shared enums for the trading cockpit.
 *
 * Since Phase 02 the domain vocabulary lives in lib/domain (canonical,
 * portable schemas); this module re-exports it so Phase 01 imports keep
 * working. Only client-side concepts (connection, environment) are defined
 * here — they never cross the wire to the backend or agents.
 */

export type {
  AgentState,
  Bias,
  ExecutionReportStatus,
  Side,
  SignalStatus,
  TradingSession,
} from "@/lib/domain";

/** Backward-compatible alias: the domain now calls this union RiskMode. */
export type { RiskMode as RiskState } from "@/lib/domain";

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
