/**
 * Payload types for the realtime events the dashboard consumes in Phase 01.
 * Each payload travels inside Envelope<T> (see envelope.ts). Only the event
 * families the cockpit renders today are typed here; Phase 02 extends this.
 */

import type {
  AccountSummary,
  CockpitAlert,
  ExecutionReport,
  MarketContext,
  Position,
  RiskStatus,
  StrategySignal,
} from "./snapshots";

export interface MarketTickPayload {
  symbol: string;
  bid: number;
  ask: number;
}

export interface AccountSnapshotPayload {
  account: AccountSummary;
}

export interface PositionsSnapshotPayload {
  positions: Position[];
}

export interface MarketContextUpdatedPayload {
  context: MarketContext;
}

export interface SignalCreatedPayload {
  signal: StrategySignal;
}

export interface SignalUpdatedPayload {
  signalId: string;
  status: StrategySignal["status"];
  riskDecision: string | null;
}

export interface RiskStateUpdatedPayload {
  risk: RiskStatus;
}

export interface AgentHeartbeatPayload {
  agentId: string;
  latencyMs: number;
}

export interface AgentConnectionPayload {
  agentId: string;
}

export interface ExecutionReportPayload {
  report: ExecutionReport;
}

export interface AlertPayload {
  alert: CockpitAlert;
}
