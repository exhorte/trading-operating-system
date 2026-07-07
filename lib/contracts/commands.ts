/**
 * Wire payloads for commands: execution.command.* toward agents and
 * dashboard.* toward the server. Each travels inside Envelope<T>
 * (see envelope.ts); domain shapes come from lib/domain.
 */

import type {
  CancelOrderCommand,
  CloseAllCommand,
  ClosePositionCommand,
  CommandAck,
  ModifyPositionCommand,
  PlaceOrderCommand,
  SymbolCode,
  Timeframe,
} from "@/lib/domain";

// execution.command.* payloads — the domain command is the payload.
export interface PlaceOrderCommandPayload {
  command: PlaceOrderCommand;
}

export interface ModifyPositionCommandPayload {
  command: ModifyPositionCommand;
}

export interface ClosePositionCommandPayload {
  command: ClosePositionCommand;
}

export interface CloseAllCommandPayload {
  command: CloseAllCommand;
}

export interface CancelOrderCommandPayload {
  command: CancelOrderCommand;
}

/** execution.command.acknowledged / execution.command.rejected */
export interface CommandAckPayload {
  ack: CommandAck;
}

/**
 * Subscription groups a realtime consumer can join. Mirrors the cockpit
 * panels and the server's future SignalR groups.
 */
export type SubscriptionTopic =
  | "market"
  | "analysis"
  | "signals"
  | "risk"
  | "execution"
  | "agents"
  | "account"
  | "alerts";

/** dashboard.subscribe / dashboard.unsubscribe */
export interface RealtimeSubscription {
  topics: SubscriptionTopic[];
  /** Empty array means all symbols the account trades. */
  symbols: SymbolCode[];
  /** Empty array means the server's default timeframes. */
  timeframes: Timeframe[];
}

/** dashboard.snapshot.requested — full resync after connect/reconnect. */
export interface SnapshotRequestPayload {
  topics: SubscriptionTopic[];
}

/** dashboard.alert.acknowledged */
export interface AlertAcknowledgedPayload {
  alertId: string;
}
