/**
 * Realtime message envelope.
 * Mirrors context/realtime/event_contracts.md — every realtime message,
 * mock or real, travels inside this envelope.
 */

export type EventType =
  // market data
  | "market.tick"
  | "market.candle.opened"
  | "market.candle.closed"
  | "market.spread.updated"
  | "market.symbol.metadata"
  // analysis
  | "analysis.market_context.updated"
  | "analysis.liquidity.swept"
  | "analysis.fvg.detected"
  | "analysis.structure.shifted"
  | "analysis.bias.updated"
  // strategy
  | "strategy.signal.created"
  | "strategy.signal.cancelled"
  | "strategy.setup.expired"
  // risk
  | "risk.state.updated"
  | "risk.decision.made"
  | "risk.command.approved"
  | "risk.command.rejected"
  | "risk.lockout.enabled"
  | "risk.lockout.cleared"
  // execution commands
  | "execution.command.place_order"
  | "execution.command.modify_position"
  | "execution.command.close_position"
  | "execution.command.close_all"
  | "execution.command.cancel_order"
  // execution reports
  | "execution.command.acknowledged"
  | "execution.command.rejected"
  | "execution.order.submitted"
  | "execution.order.filled"
  | "execution.order.partially_filled"
  | "execution.order.failed"
  | "execution.position.opened"
  | "execution.position.modified"
  | "execution.position.closed"
  // agent
  | "agent.connected"
  | "agent.heartbeat"
  | "agent.disconnected"
  | "agent.snapshot.account"
  | "agent.snapshot.positions"
  | "agent.error"
  // dashboard
  | "dashboard.subscribe"
  | "dashboard.unsubscribe"
  | "dashboard.snapshot.requested"
  | "dashboard.alert.acknowledged";

export interface Envelope<TPayload = unknown> {
  messageId: string;
  correlationId: string;
  causationId: string | null;
  type: EventType;
  schemaVersion: number;
  source: string;
  target: string;
  sentAt: string;
  payload: TPayload;
}
