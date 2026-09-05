/**
 * Execution models: orders, positions, trades, the command/ack/report
 * protocol, and the execution agent. Commands are a discriminated union on
 * `kind` so the server, .NET hub, and MQL5 agent can switch exhaustively.
 * Idempotency rules: context/realtime/event_contracts.md.
 */

import type {
  AccountId,
  AgentId,
  CommandId,
  OrderId,
  PositionId,
  RiskApprovalId,
  Side,
  SignalId,
  StrategyId,
  SymbolCode,
  TradeId,
  UtcTimestamp,
} from "./primitives";

export type OrderType = "market" | "limit" | "stop";

export type OrderStatus =
  | "pending"
  | "submitted"
  | "partially_filled"
  | "filled"
  | "cancelled"
  | "rejected"
  | "expired";

/** An instruction sent to an execution venue, tracked through its lifecycle. */
export interface Order {
  orderId: OrderId;
  accountId: AccountId;
  agentId: AgentId;
  /** Command that created this order (audit link). */
  commandId: CommandId;
  symbol: SymbolCode;
  side: Side;
  orderType: OrderType;
  /** Requested volume in lots. */
  volume: number;
  /** Null for market orders. */
  limitPrice: number | null;
  stopLoss: number;
  takeProfit: number;
  status: OrderStatus;
  /** Broker-side ticket once submitted, else null. */
  brokerOrderId: string | null;
  filledVolume: number;
  averageFillPrice: number | null;
  createdAt: UtcTimestamp;
  updatedAt: UtcTimestamp;
}

/** Open market exposure with explicit risk levels — SL is mandatory. */
export interface Position {
  positionId: PositionId;
  accountId: AccountId;
  agentId: AgentId;
  symbol: SymbolCode;
  side: Side;
  volume: number;
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
  /** Broker-side position ticket. */
  brokerPositionId: string | null;
  /** Signal that opened the position (audit link); null for manual trades. */
  signalId: SignalId | null;
  strategyId: StrategyId | null;
  openedAt: UtcTimestamp;
}

/** Completed position lifecycle with result and attribution. */
export interface Trade {
  tradeId: TradeId;
  accountId: AccountId;
  positionId: PositionId;
  symbol: SymbolCode;
  side: Side;
  volume: number;
  entryPrice: number;
  exitPrice: number;
  stopLoss: number;
  takeProfit: number;
  /** Realized P&L in account currency, commissions/swap included. */
  realizedPnl: number;
  /** Result as a multiple of the initial risk (R). */
  rMultiple: number;
  signalId: SignalId | null;
  strategyId: StrategyId | null;
  openedAt: UtcTimestamp;
  closedAt: UtcTimestamp;
}

/** Fields shared by every execution command. */
interface ExecutionCommandBase {
  /** Stable id agents use for deduplication; reports must echo it. */
  commandId: CommandId;
  accountId: AccountId;
  agentId: AgentId;
  /** Risk approval that authorized this command — mandatory, no bypass. */
  riskApprovalId: RiskApprovalId;
  /** Agents must refuse the command after this time. */
  expiresAt: UtcTimestamp;
  issuedAt: UtcTimestamp;
}

export interface PlaceOrderCommand extends ExecutionCommandBase {
  kind: "place_order";
  symbol: SymbolCode;
  side: Side;
  orderType: OrderType;
  volume: number;
  limitPrice: number | null;
  stopLoss: number;
  takeProfit: number;
  signalId: SignalId | null;
  strategyId: StrategyId | null;
}

export interface ModifyPositionCommand extends ExecutionCommandBase {
  kind: "modify_position";
  positionId: PositionId;
  /** Null leaves the level unchanged. */
  stopLoss: number | null;
  takeProfit: number | null;
}

export interface ClosePositionCommand extends ExecutionCommandBase {
  kind: "close_position";
  positionId: PositionId;
  /** Null closes the full volume. */
  volume: number | null;
}

export interface CloseAllCommand extends ExecutionCommandBase {
  kind: "close_all";
  /** Null closes across all symbols. */
  symbol: SymbolCode | null;
  reason: string;
}

export interface CancelOrderCommand extends ExecutionCommandBase {
  kind: "cancel_order";
  orderId: OrderId;
}

export type ExecutionCommand =
  | PlaceOrderCommand
  | ModifyPositionCommand
  | ClosePositionCommand
  | CloseAllCommand
  | CancelOrderCommand;

/** Agent's immediate receipt for a command, before any broker outcome. */
export interface CommandAck {
  commandId: CommandId;
  agentId: AgentId;
  status: "accepted" | "rejected" | "duplicate" | "expired";
  /** Populated when status is not "accepted". */
  reason: string | null;
  receivedAt: UtcTimestamp;
}

export type ExecutionReportStatus =
  | "acknowledged"
  | "submitted"
  /** Observe-mode outcome: the command was validated end-to-end but no broker
   *  order exists. Never rendered or treated as a fill. */
  | "simulated"
  | "filled"
  | "partially_filled"
  | "failed"
  | "position_opened"
  | "position_modified"
  | "position_closed";

/** Broker-side outcome of a command, reconciled against intent by the server. */
export interface ExecutionReport {
  reportId: string;
  commandId: CommandId;
  accountId: AccountId;
  agentId: AgentId;
  symbol: SymbolCode;
  side: Side;
  status: ExecutionReportStatus;
  brokerOrderId: string | null;
  brokerPositionId: string | null;
  filledVolume: number | null;
  averagePrice: number | null;
  /** Raw broker return code, e.g. "TRADE_RETCODE_DONE". */
  brokerRetcode: string | null;
  detail: string;
  reportedAt: UtcTimestamp;
}

export type AgentState = "connected" | "degraded" | "disconnected";

/** An execution/telemetry endpoint (MT5 EA first; later cTrader, IB, FIX). */
export interface ExecutionAgent {
  agentId: AgentId;
  accountId: AccountId;
  platform: "mt5" | "ctrader" | "ib" | "fix" | "mock";
  version: string;
  state: AgentState;
  latencyMs: number;
  lastHeartbeatAt: UtcTimestamp | null;
  connectedAt: UtcTimestamp | null;
}
