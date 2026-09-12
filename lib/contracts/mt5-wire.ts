/**
 * MT5 edge wire protocol — the lean, versioned JSON the MT5 agent exchanges
 * with the WebSocket Gateway over WSS. This is DELIBERATELY simpler than the
 * internal Envelope<T> (lib/contracts/envelope.ts): flat fields, `version`
 * instead of `schemaVersion`, epoch `time`, uppercase side, `id` instead of
 * `commandId`, and no correlation/causation metadata. The gateway enriches
 * inbound messages into Envelope<T> + domain models and flattens outbound
 * commands back to this form (see context/realtime/mt5_wire_protocol.md).
 *
 * Canonical schema per ADR 0004/0005: the EA (MQL5) and the gateway (.NET)
 * mirror these types. No classes, no Date — plain shapes only.
 */

import type { SymbolCode } from "@/lib/domain";

/** Bumped when the lean edge protocol changes shape. */
export type Mt5WireVersion = 1;

/** Side is uppercase at the MT5 edge; the gateway lowercases it to domain Side. */
export type Mt5Side = "BUY" | "SELL";

/**
 * Execution mode carried by the agent. `observe` never touches the broker and
 * replies SIMULATED; the terminal action is the only difference between modes.
 *
 * EA-05: renamed the third rung from this type's original `"live"` to
 * `"confirm"`, to match ADR 0010's ladder (OBSERVE -> PAPER -> CONFIRM) —
 * this type predates that ADR. Pure rename: nothing in the repo branches on
 * the literal `"live"` value (checked before renaming), and `"confirm"`
 * names what actually matters here — every order in this rung still
 * requires explicit human validation (EA-07) — rather than just "is this a
 * real-money account", which `lib/domain/account.ts::AccountKind` already
 * covers on its own, unrelated axis.
 */
export type Mt5ExecutionMode = "observe" | "paper" | "confirm";

export type Mt5MessageType =
  // agent → gateway (telemetry / lifecycle)
  | "agent.hello"
  | "agent.heartbeat"
  | "agent.error"
  | "market.tick"
  | "market.candle"
  | "account.snapshot"
  | "positions.snapshot"
  | "position.opened"
  | "position.closed"
  | "execution.ack"
  | "execution.report"
  // gateway → agent (control / commands)
  | "execution.order"
  | "execution.modify"
  | "execution.close"
  | "execution.close_all"
  | "execution.cancel"
  | "control.set_mode"
  | "control.resync";

/** Fields present on every lean message. */
export interface Mt5Message {
  version: Mt5WireVersion;
  type: Mt5MessageType;
  accountId: string;
  /** Unix epoch milliseconds, UTC. Refined from the seconds-based example to
   *  keep tick ordering unambiguous; the gateway converts to ISO UtcTimestamp. */
  time: number;
}

// --- agent → gateway ---

/** Broker/account capabilities sent on connect and after every reconnect. */
export interface Mt5HelloMessage extends Mt5Message {
  type: "agent.hello";
  agentId: string;
  symbol: SymbolCode;
  broker: string;
  server: string;
  /** Order types the broker/account supports, e.g. ["market","limit","stop"]. */
  orderTypes: string[];
  minVolume: number;
  maxVolume: number;
  volumeStep: number;
  /** Broker filling mode label, e.g. "IOC" | "FOK" | "RETURN". */
  fillingMode: string;
  /** Minimum stop distance in points the broker enforces. */
  stopsLevelPoints: number;
  /** Mode the agent booted with; the gateway/engine reconcile against config. */
  mode: Mt5ExecutionMode;
  agentVersion: string;
  /** T02a: broker server UTC offset, resolved fresh at every hello — never
   *  hardcoded, since it shifts with DST. Source of the trading-day anchor. */
  serverUtcOffsetMinutes: number;
}

export interface Mt5HeartbeatMessage extends Mt5Message {
  type: "agent.heartbeat";
  agentId: string;
  /** Round-trip latency the agent last measured to the gateway, ms. */
  latencyMs: number;
}

export interface Mt5ErrorMessage extends Mt5Message {
  type: "agent.error";
  agentId: string;
  code: string;
  message: string;
}

export interface Mt5TickMessage extends Mt5Message {
  type: "market.tick";
  symbol: SymbolCode;
  bid: number;
  ask: number;
}

export interface Mt5CandleMessage extends Mt5Message {
  type: "market.candle";
  symbol: SymbolCode;
  /** Timeframe label as MT5 reports it, e.g. "M5"; gateway maps to Timeframe. */
  timeframe: string;
  /** Candle open time, epoch milliseconds UTC. */
  openTime: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  /** False while the candle is still forming. */
  closed: boolean;
}

export interface Mt5AccountSnapshotMessage extends Mt5Message {
  type: "account.snapshot";
  balance: number;
  equity: number;
  margin: number;
  freeMargin: number;
  currency: string;
}

export interface Mt5PositionSnapshot {
  brokerPositionId: string;
  symbol: SymbolCode;
  side: Mt5Side;
  volume: number;
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
  /** Floating P&L in account currency. */
  floatingPnl: number;
}

export interface Mt5PositionsSnapshotMessage extends Mt5Message {
  type: "positions.snapshot";
  positions: Mt5PositionSnapshot[];
}

/**
 * T05: a genuinely new ticket, observer-detected (server-side diff — see
 * mt5_observer.py::poll_positions/diff_position_ids). Replaces the old
 * client-side detection (T02a) so entry capture and trade counting no longer
 * depend on a browser tab being open. `openedAt` is detection time, not
 * MT5's true fill time — the wire has never carried that field.
 */
export interface Mt5PositionOpenedMessage extends Mt5Message {
  type: "position.opened";
  brokerPositionId: string;
  symbol: SymbolCode;
  side: Mt5Side;
  volume: number;
  entryPrice: number;
  stopLoss: number;
  takeProfit: number;
  /** Epoch ms UTC, detection time. */
  openedAt: number;
}

/**
 * T02b: a position that fully closed since the last poll (observer-detected,
 * never client-derived — only the terminal's deal history has the true net
 * P&L across every partial close). `realizedPnl` is already the sum of
 * profit + commission + swap over ALL deals on the position.
 */
export interface Mt5PositionClosedMessage extends Mt5Message {
  type: "position.closed";
  brokerPositionId: string;
  symbol: SymbolCode;
  side: Mt5Side;
  volume: number;
  realizedPnl: number;
  /** T05: volume-weighted average across every exit deal — marks the exit
   *  fill on a rendered capture. */
  exitPrice: number;
  /** Epoch ms UTC of the last exit deal. */
  closedAt: number;
}

/** Immediate receipt for a command, before any broker outcome. */
export interface Mt5AckMessage extends Mt5Message {
  type: "execution.ack";
  /** Echoes the command `id`. */
  commandId: string;
  status: "ACCEPTED" | "REJECTED" | "DUPLICATE" | "EXPIRED";
  /** Populated when status is not ACCEPTED. */
  reason: string | null;
}

/** Terminal outcome of a command. In `observe` mode status is "SIMULATED". */
export interface Mt5ReportMessage extends Mt5Message {
  type: "execution.report";
  /** Echoes the command `id`. */
  commandId: string;
  status:
    | "SIMULATED"
    | "FILLED"
    | "PARTIALLY_FILLED"
    | "MODIFIED"
    | "CLOSED"
    | "FAILED"
    | "REJECTED";
  symbol: SymbolCode;
  side: Mt5Side;
  brokerOrderId: string | null;
  brokerPositionId: string | null;
  filledVolume: number | null;
  averagePrice: number | null;
  /** Raw MT5 return code, e.g. "TRADE_RETCODE_DONE". */
  brokerRetcode: string | null;
  detail: string;
}

// --- gateway → agent ---

/** Fields shared by every command the gateway sends down. */
interface Mt5CommandBase extends Mt5Message {
  /** Stable command id the agent dedupes on and echoes in ack/report. */
  id: string;
  /** Agent must refuse the command after this epoch-ms instant. */
  expiresAt: number;
}

export interface Mt5OrderCommand extends Mt5CommandBase {
  type: "execution.order";
  symbol: SymbolCode;
  side: Mt5Side;
  /** "MARKET" | "LIMIT" | "STOP" at the edge. */
  orderType: "MARKET" | "LIMIT" | "STOP";
  volume: number;
  /** Null for market orders. */
  limitPrice: number | null;
  sl: number;
  tp: number;
}

export interface Mt5ModifyCommand extends Mt5CommandBase {
  type: "execution.modify";
  brokerPositionId: string;
  /** Null leaves the level unchanged. */
  sl: number | null;
  tp: number | null;
}

export interface Mt5CloseCommand extends Mt5CommandBase {
  type: "execution.close";
  brokerPositionId: string;
  /** Null closes the full volume. */
  volume: number | null;
}

export interface Mt5CloseAllCommand extends Mt5CommandBase {
  type: "execution.close_all";
  /** Null closes across all symbols. */
  symbol: SymbolCode | null;
  reason: string;
}

export interface Mt5CancelCommand extends Mt5CommandBase {
  type: "execution.cancel";
  brokerOrderId: string;
}

/** Switch the agent's execution mode at runtime (e.g. observe → paper). */
export interface Mt5SetModeCommand extends Mt5CommandBase {
  type: "control.set_mode";
  mode: Mt5ExecutionMode;
}

/** Ask the agent to resend account + positions snapshots. */
export interface Mt5ResyncCommand extends Mt5CommandBase {
  type: "control.resync";
}

export type Mt5InboundMessage =
  | Mt5HelloMessage
  | Mt5HeartbeatMessage
  | Mt5ErrorMessage
  | Mt5TickMessage
  | Mt5CandleMessage
  | Mt5AccountSnapshotMessage
  | Mt5PositionsSnapshotMessage
  | Mt5PositionOpenedMessage
  | Mt5PositionClosedMessage
  | Mt5AckMessage
  | Mt5ReportMessage;

export type Mt5OutboundMessage =
  | Mt5OrderCommand
  | Mt5ModifyCommand
  | Mt5CloseCommand
  | Mt5CloseAllCommand
  | Mt5CancelCommand
  | Mt5SetModeCommand
  | Mt5ResyncCommand;

export type Mt5WireMessage = Mt5InboundMessage | Mt5OutboundMessage;
