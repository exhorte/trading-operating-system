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
  | "execution.order.simulated"
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
  | "dashboard.alert.acknowledged"
  // journal (T04: dashboard-originated, published through the same
  // whitelisted PublishEvent path as strategy.signal.created)
  | "journal.ticket.created"
  // T02a: journal.position.opened and risk.day_anchor.equity_observed are
  // dashboard-observed facts (published like the ticket above);
  // risk.day_anchor.resolved is Gateway-only (needs the MT5 terminal's
  // server-UTC offset) — never published by a dashboard.
  | "journal.position.opened"
  | "risk.day_anchor.resolved"
  | "risk.day_anchor.equity_observed"
  | "risk.lockout.acknowledged"
  // T02b: Gateway-only, same category as risk.day_anchor.resolved — only the
  // observer's deal history knows a position truly closed.
  | "journal.trade_closed"
  // T03: Gateway-only — the backend polls FRED and owns the calendar cache;
  // never client-published.
  | "market.calendar.updated";

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
