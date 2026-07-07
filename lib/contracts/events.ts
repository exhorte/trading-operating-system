/**
 * Payload types for realtime events, plus the EventPayloadMap that pairs
 * every EventType with its payload so producers and consumers can be typed
 * exhaustively. Each payload travels inside Envelope<T> (see envelope.ts).
 *
 * Two payload styles coexist by design (context/realtime/dashboard_realtime_model.md):
 * - dashboard-facing events carry read models from snapshots.ts
 * - backend/agent-facing events carry canonical domain shapes from lib/domain
 *
 * Known Phase 01 shortcut: the mock feed publishes execution.command.acknowledged
 * with an ExecutionReportPayload for the cockpit feed; the canonical agent-channel
 * payload is CommandAckPayload (see commands.ts). To reconcile when the store
 * adopts EventPayloadMap.
 */

import type { Envelope, EventType } from "./envelope";
import type {
  AccountSummary,
  CockpitAlert,
  ExecutionReport,
  MarketContext,
  Position,
  RiskStatus,
  StrategySignal,
} from "./snapshots";
import type {
  AlertAcknowledgedPayload,
  CancelOrderCommandPayload,
  CloseAllCommandPayload,
  ClosePositionCommandPayload,
  ModifyPositionCommandPayload,
  PlaceOrderCommandPayload,
  RealtimeSubscription,
  SnapshotRequestPayload,
} from "./commands";
import type {
  AccountId,
  Bias,
  Candle,
  FairValueGap,
  LiquidityLevel,
  SpreadSample,
  StructureShift,
  SymbolCode,
  SymbolMetadata,
  Timeframe,
  UtcTimestamp,
} from "@/lib/domain";

// --- market data ---

export interface MarketTickPayload {
  symbol: string;
  bid: number;
  ask: number;
}

export interface MarketCandlePayload {
  candle: Candle;
}

export interface SpreadUpdatedPayload {
  spread: SpreadSample;
}

export interface SymbolMetadataPayload {
  metadata: SymbolMetadata;
}

// --- analysis ---

export interface MarketContextUpdatedPayload {
  context: MarketContext;
}

export interface LiquiditySweptPayload {
  level: LiquidityLevel;
}

export interface FvgDetectedPayload {
  fvg: FairValueGap;
}

export interface StructureShiftedPayload {
  shift: StructureShift;
}

export interface BiasUpdatedPayload {
  symbol: SymbolCode;
  timeframe: Timeframe;
  bias: Bias;
  previousBias: Bias;
}

// --- strategy ---

export interface SignalCreatedPayload {
  signal: StrategySignal;
}

export interface SignalUpdatedPayload {
  signalId: string;
  status: StrategySignal["status"];
  riskDecision: string | null;
}

export interface SignalCancelledPayload {
  signalId: string;
  reason: string;
}

export interface SetupExpiredPayload {
  signalId: string;
}

// --- risk ---

export interface RiskStateUpdatedPayload {
  risk: RiskStatus;
}

export interface RiskLockoutEnabledPayload {
  accountId: AccountId;
  reason: string;
  /** Null when the lockout requires manual clearance. */
  lockoutUntil: UtcTimestamp | null;
}

export interface RiskLockoutClearedPayload {
  accountId: AccountId;
}

// --- agent ---

export interface AgentHeartbeatPayload {
  agentId: string;
  latencyMs: number;
}

export interface AgentConnectionPayload {
  agentId: string;
}

export interface AgentErrorPayload {
  agentId: string;
  code: string;
  message: string;
}

export interface AccountSnapshotPayload {
  account: AccountSummary;
}

export interface PositionsSnapshotPayload {
  positions: Position[];
}

// --- execution reports (dashboard feed) ---

export interface ExecutionReportPayload {
  report: ExecutionReport;
}

// --- alerts ---

export interface AlertPayload {
  alert: CockpitAlert;
}

/**
 * Exhaustive EventType → payload registry. The future SignalR client and the
 * mock client both conform to this map; adding an EventType without a payload
 * here is a compile error.
 */
export interface EventPayloadMap extends Record<EventType, unknown> {
  "market.tick": MarketTickPayload;
  "market.candle.opened": MarketCandlePayload;
  "market.candle.closed": MarketCandlePayload;
  "market.spread.updated": SpreadUpdatedPayload;
  "market.symbol.metadata": SymbolMetadataPayload;
  "analysis.market_context.updated": MarketContextUpdatedPayload;
  "analysis.liquidity.swept": LiquiditySweptPayload;
  "analysis.fvg.detected": FvgDetectedPayload;
  "analysis.structure.shifted": StructureShiftedPayload;
  "analysis.bias.updated": BiasUpdatedPayload;
  "strategy.signal.created": SignalCreatedPayload;
  "strategy.signal.cancelled": SignalCancelledPayload;
  "strategy.setup.expired": SetupExpiredPayload;
  "risk.state.updated": RiskStateUpdatedPayload;
  "risk.command.approved": SignalUpdatedPayload;
  "risk.command.rejected": SignalUpdatedPayload;
  "risk.lockout.enabled": RiskLockoutEnabledPayload;
  "risk.lockout.cleared": RiskLockoutClearedPayload;
  "execution.command.place_order": PlaceOrderCommandPayload;
  "execution.command.modify_position": ModifyPositionCommandPayload;
  "execution.command.close_position": ClosePositionCommandPayload;
  "execution.command.close_all": CloseAllCommandPayload;
  "execution.command.cancel_order": CancelOrderCommandPayload;
  "execution.command.acknowledged": ExecutionReportPayload;
  "execution.command.rejected": ExecutionReportPayload;
  "execution.order.submitted": ExecutionReportPayload;
  "execution.order.filled": ExecutionReportPayload;
  "execution.order.partially_filled": ExecutionReportPayload;
  "execution.order.failed": ExecutionReportPayload;
  "execution.position.opened": ExecutionReportPayload;
  "execution.position.modified": ExecutionReportPayload;
  "execution.position.closed": ExecutionReportPayload;
  "agent.connected": AgentConnectionPayload;
  "agent.heartbeat": AgentHeartbeatPayload;
  "agent.disconnected": AgentConnectionPayload;
  "agent.snapshot.account": AccountSnapshotPayload;
  "agent.snapshot.positions": PositionsSnapshotPayload;
  "agent.error": AgentErrorPayload;
  "dashboard.subscribe": RealtimeSubscription;
  "dashboard.unsubscribe": RealtimeSubscription;
  "dashboard.snapshot.requested": SnapshotRequestPayload;
  "dashboard.alert.acknowledged": AlertAcknowledgedPayload;
}

/** An envelope whose payload type is derived from its event type. */
export type KnownEnvelope<T extends EventType = EventType> = Envelope<
  EventPayloadMap[T]
> & { type: T };
