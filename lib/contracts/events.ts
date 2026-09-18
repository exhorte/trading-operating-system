/**
 * Payload types for realtime events, plus the EventPayloadMap that pairs
 * every EventType with its payload so producers and consumers can be typed
 * exhaustively. Each payload travels inside Envelope<T> (see envelope.ts).
 *
 * Two payload styles coexist by design (context/realtime/dashboard_realtime_model.md):
 * - dashboard-facing events carry read models from snapshots.ts
 * - backend/agent-facing events carry canonical domain shapes from lib/domain
 *
 * Phase 09 reconciled the old Phase 01 shortcut: execution.command.acknowledged
 * and .rejected now carry the canonical CommandAckPayload (commands.ts), and
 * observe-mode outcomes travel as execution.order.simulated — never disguised
 * as fills.
 */

import type { Envelope, EventType } from "./envelope";
import type {
  AccountSummary,
  CockpitAlert,
  ExecutionReport,
  MarketContext,
  Position,
  RiskStatus,
} from "./snapshots";
import type {
  AlertAcknowledgedPayload,
  CancelOrderCommandPayload,
  CloseAllCommandPayload,
  ClosePositionCommandPayload,
  CommandAckPayload,
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
  UpcomingRelease,
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

// --- risk ---

export interface RiskStateUpdatedPayload {
  risk: RiskStatus;
}

export interface RiskLockoutEnabledPayload {
  /** T02a: the ledger is the source of truth for "locked now" — never re-derived. */
  lockoutId: string;
  accountId: AccountId;
  reason: string;
  since: UtcTimestamp;
  /** Null when the lockout requires manual/next-day clearance (daily loss,
   *  max trades, kill switch). Set when it auto-expires (T02b's pause). */
  until: UtcTimestamp | null;
}

export interface RiskLockoutClearedPayload {
  accountId: AccountId;
  /** "kill-switch-ack" | "next-day-reset" | "manual" — audit trail, not a union
   *  the reader needs to exhaust. */
  clearedBy: string;
}

/** T02a: the trader's proof of having closed positions manually — the kill
 *  switch never sends a close_all command, so this ack is the only record. */
export interface RiskLockoutAcknowledgedPayload {
  accountId: AccountId;
  lockoutId: string;
  acknowledgedAt: UtcTimestamp;
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

// --- T02a: trading-day anchor + real trade counting ---

/** Gateway-originated only — needs the MT5 terminal's server-UTC offset. */
export interface DayAnchorResolvedPayload {
  accountId: AccountId;
  startsAtUtc: UtcTimestamp;
}

/** Dashboard-observed: the first live equity seen on/after the anchor. */
export interface DayAnchorEquityObservedPayload {
  accountId: AccountId;
  startsAtUtc: UtcTimestamp;
  equity: number;
}

/**
 * One real position opened (brokerPositionId first seen). Gateway-originated
 * only since T05 (server-side diff, mt5_observer.py::poll_positions) — never
 * client-published anymore (was client-detected in T02a). Carries the full
 * fact so it's self-contained for audit/replay: T02a only needed the count,
 * but T05's capture-fact write needs entryPrice/stopLoss/takeProfit and
 * can't rely on a live GatewayState lookup for a historical envelope.
 */
export interface PositionOpenedPayload {
  accountId: AccountId;
  brokerPositionId: string;
  symbol: SymbolCode;
  side: "buy" | "sell";
  volume: number;
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
  openedAt: UtcTimestamp;
}

/**
 * T02b: Gateway-originated only (like DayAnchorResolvedPayload) — a position
 * fully closed, as observed on the MT5 terminal. `realizedPnl` already sums
 * profit + commission + swap over every deal on the position; see
 * T02-lockout.md for the partial-close pitfall this guards against.
 */
export interface TradeClosedPayload {
  accountId: AccountId;
  brokerPositionId: string;
  symbol: SymbolCode;
  side: "buy" | "sell";
  volume: number;
  realizedPnl: number;
  closedAt: UtcTimestamp;
}

/**
 * T02c: a position opened while risk_lockouts already showed an active lock
 * for this account — the live counterpart to T07's after-the-fact
 * detectLockoutViolation (lib/compliance/violations.ts). Gateway-originated
 * only, same category as PositionOpenedPayload/TradeClosedPayload above.
 * Self-contained for audit/replay, not just a pointer back to other tables.
 */
export interface LockoutViolatedPayload {
  accountId: AccountId;
  brokerPositionId: string;
  symbol: SymbolCode;
  side: "buy" | "sell";
  lockoutId: string;
  lockoutReason: string;
  openedAt: UtcTimestamp;
}

/**
 * Live state of the EA-05 execution agent's TCP connection
 * (Mt5AgentServer.IsConnected), Gateway-originated. The only honest answer to
 * "can an order actually reach MT5 right now" — AgentStatus/`agents` carries
 * the read-only observer's hello and says nothing about execution, which is
 * what connectionGate was reading by mistake until 2026-09-18.
 */
export interface ExecutionAgentConnectionPayload {
  connected: boolean;
}

/**
 * T03: Gateway-originated only — the backend owns the FRED poll + cache
 * (context/product/tools/T03-gate-news.md). Broadcast on every refresh cycle
 * whether or not the list actually changed (same idempotent-recheck pattern
 * as risk.day_anchor.resolved), always the FULL current upcoming list, never
 * a delta — the client's local state is always a clean replace.
 */
export interface CalendarUpdatedPayload {
  /** Null when the backend's FRED cache has never been populated — distinct
   *  from a successful sync currently finding nothing upcoming ([]). */
  releases: UpcomingRelease[] | null;
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
  "risk.state.updated": RiskStateUpdatedPayload;
  "risk.lockout.enabled": RiskLockoutEnabledPayload;
  "risk.lockout.cleared": RiskLockoutClearedPayload;
  "execution.command.place_order": PlaceOrderCommandPayload;
  "execution.command.modify_position": ModifyPositionCommandPayload;
  "execution.command.close_position": ClosePositionCommandPayload;
  "execution.command.close_all": CloseAllCommandPayload;
  "execution.command.cancel_order": CancelOrderCommandPayload;
  "execution.command.acknowledged": CommandAckPayload;
  "execution.command.rejected": CommandAckPayload;
  "execution.order.simulated": ExecutionReportPayload;
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
  "journal.position.opened": PositionOpenedPayload;
  "risk.day_anchor.resolved": DayAnchorResolvedPayload;
  "risk.day_anchor.equity_observed": DayAnchorEquityObservedPayload;
  "risk.lockout.acknowledged": RiskLockoutAcknowledgedPayload;
  "journal.trade_closed": TradeClosedPayload;
  "journal.lockout_violated": LockoutViolatedPayload;
  "execution.agent.connection": ExecutionAgentConnectionPayload;
  "market.calendar.updated": CalendarUpdatedPayload;
}

/** An envelope whose payload type is derived from its event type. */
export type KnownEnvelope<T extends EventType = EventType> = Envelope<
  EventPayloadMap[T]
> & { type: T };
