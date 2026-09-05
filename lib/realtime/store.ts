/**
 * Cockpit state store: latest known state per subscription group, mutated by
 * enveloped realtime events (snapshot + events pattern from
 * context/realtime/dashboard_realtime_model.md).
 *
 * UI code depends on this store and the RealtimeClient interface only —
 * never on the mock implementation — so the future SignalR client can be
 * swapped in without touching components.
 */

import type { Envelope } from "@/lib/contracts/envelope";
import type { ConnectionState, Environment } from "@/lib/contracts/enums";
import type {
  AccountSummary,
  AgentStatus,
  CockpitAlert,
  ExecutionCommandView,
  ExecutionReport,
  MarketContext,
  PnlCalendarDay,
  Position,
  RiskDecisionView,
  RiskStatus,
  StrategySignal,
} from "@/lib/contracts/snapshots";
import type {
  CommandAckPayload,
  PlaceOrderCommandPayload,
} from "@/lib/contracts/commands";
import type {
  AccountSnapshotPayload,
  AgentHeartbeatPayload,
  CalendarUpdatedPayload,
  ExecutionReportPayload,
  MarketContextUpdatedPayload,
  MarketTickPayload,
  PositionsSnapshotPayload,
  RiskDecisionMadePayload,
  RiskLockoutAcknowledgedPayload,
  RiskLockoutEnabledPayload,
  RiskStateUpdatedPayload,
  SignalCreatedPayload,
  SignalUpdatedPayload,
  TicketCreatedPayload,
} from "@/lib/contracts/events";
import type { UpcomingRelease } from "@/lib/domain/risk";
import type { ActiveLockout } from "@/lib/risk/lockout";

export interface CockpitSnapshot {
  connection: ConnectionState;
  environment: Environment;
  account: AccountSummary | null;
  positions: Position[];
  risk: RiskStatus | null;
  marketContext: MarketContext | null;
  signals: StrategySignal[];
  /** Audit-grade risk decisions keyed by signalId (Signal → Risk Review). */
  riskDecisions: Record<string, RiskDecisionView>;
  /** Execution command lifecycle keyed by commandId (Phase 09 bridge audit). */
  commands: Record<string, ExecutionCommandView>;
  agents: AgentStatus[];
  executionReports: ExecutionReport[];
  pnlCalendar: PnlCalendarDay[];
  alerts: CockpitAlert[];
  lastHeartbeatAt: string | null;
  /**
   * T04: ticketIds that have echoed back through the event stream — i.e.
   * actually broadcast (and, best-effort, persisted) by the hub, not just
   * submitted by this tab. TicketPanel watches this to know whether to
   * reset the form; a ticket that never appears here was silently refused
   * or dropped (see PublishEvent / PersistenceWriter).
   */
  confirmedTicketIds: string[];
  /**
   * T02a: the ledger's current lock for this account, or null when clear.
   * Authoritative — components must not re-derive "locked" from `risk` alone.
   */
  activeLockout: ActiveLockout | null;
  /** lockoutIds this tab has seen acknowledged (kill-switch banner dismissal). */
  acknowledgedLockoutIds: string[];
  /**
   * T03: the backend's FRED cache, as of the last hydrate/market.calendar.updated.
   * Null means "never hydrated yet" — components must render this as
   * "no calendar data" (fail-closed), never as an empty, healthy calendar.
   */
  upcomingReleases: UpcomingRelease[] | null;
}

export const EMPTY_COCKPIT_SNAPSHOT: CockpitSnapshot = {
  connection: "connecting",
  environment: "mock",
  account: null,
  positions: [],
  risk: null,
  marketContext: null,
  signals: [],
  riskDecisions: {},
  commands: {},
  agents: [],
  executionReports: [],
  pnlCalendar: [],
  alerts: [],
  lastHeartbeatAt: null,
  confirmedTicketIds: [],
  activeLockout: null,
  acknowledgedLockoutIds: [],
  upcomingReleases: null,
};

const MAX_FEED_LENGTH = 20;

export class CockpitStore {
  private snapshot: CockpitSnapshot = EMPTY_COCKPIT_SNAPSHOT;

  private listeners = new Set<() => void>();

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = (): CockpitSnapshot => this.snapshot;

  setConnectionState(connection: ConnectionState): void {
    if (this.snapshot.connection !== connection) {
      this.patch({ connection });
    }
  }

  /** Initial snapshot or post-reconnect resync of every subscription group. */
  hydrate(data: Partial<CockpitSnapshot>): void {
    this.patch(data);
  }

  /** Apply one enveloped realtime event to the latest known state. */
  apply(envelope: Envelope): void {
    switch (envelope.type) {
      case "market.tick": {
        const { symbol, bid } = envelope.payload as MarketTickPayload;
        this.applyTick(symbol, bid);
        break;
      }
      case "agent.snapshot.account": {
        const { account } = envelope.payload as AccountSnapshotPayload;
        this.patch({ account });
        break;
      }
      case "agent.snapshot.positions": {
        const { positions } = envelope.payload as PositionsSnapshotPayload;
        this.patch({ positions });
        break;
      }
      case "analysis.market_context.updated": {
        const { context } = envelope.payload as MarketContextUpdatedPayload;
        this.patch({ marketContext: context });
        break;
      }
      case "strategy.signal.created": {
        const { signal } = envelope.payload as SignalCreatedPayload;
        this.patch({
          signals: [signal, ...this.snapshot.signals].slice(0, MAX_FEED_LENGTH),
        });
        break;
      }
      case "risk.decision.made": {
        const { decision } = envelope.payload as RiskDecisionMadePayload;
        this.patch({
          signals: this.snapshot.signals.map((signal) =>
            signal.signalId === decision.signalId
              ? {
                  ...signal,
                  status: decision.approved ? "approved" : "rejected",
                  riskDecision: decision.reason,
                }
              : signal,
          ),
          riskDecisions: { ...this.snapshot.riskDecisions, [decision.signalId]: decision },
        });
        break;
      }
      case "risk.command.approved":
      case "risk.command.rejected": {
        const update = envelope.payload as SignalUpdatedPayload;
        this.patch({
          signals: this.snapshot.signals.map((signal) =>
            signal.signalId === update.signalId
              ? { ...signal, status: update.status, riskDecision: update.riskDecision }
              : signal,
          ),
        });
        break;
      }
      case "risk.state.updated": {
        const { risk } = envelope.payload as RiskStateUpdatedPayload;
        this.patch({ risk });
        break;
      }
      // T04: the hub's echo of a ticket this tab (or another tab) published —
      // the only signal that PublishEvent actually broadcast it.
      case "journal.ticket.created": {
        const { ticket } = envelope.payload as TicketCreatedPayload;
        this.patch({
          confirmedTicketIds: [ticket.ticketId, ...this.snapshot.confirmedTicketIds].slice(
            0,
            MAX_FEED_LENGTH,
          ),
        });
        break;
      }
      // T02a: the ledger is authoritative — set/clear it here, never derive
      // "locked" from `risk` alone in a component.
      case "risk.lockout.enabled": {
        const { lockoutId, reason, since, until } = envelope.payload as RiskLockoutEnabledPayload;
        this.patch({ activeLockout: { lockoutId, reason, since, until } });
        break;
      }
      case "risk.lockout.cleared": {
        this.patch({ activeLockout: null });
        break;
      }
      case "risk.lockout.acknowledged": {
        const { lockoutId } = envelope.payload as RiskLockoutAcknowledgedPayload;
        this.patch({
          acknowledgedLockoutIds: [lockoutId, ...this.snapshot.acknowledgedLockoutIds].slice(
            0,
            MAX_FEED_LENGTH,
          ),
        });
        break;
      }
      // T03: Gateway-originated, always the full current list (never a delta) —
      // a plain replace, same as risk.lockout.enabled overwriting the ledger.
      case "market.calendar.updated": {
        const { releases } = envelope.payload as CalendarUpdatedPayload;
        this.patch({ upcomingReleases: releases });
        break;
      }
      case "agent.heartbeat": {
        const { agentId, latencyMs } = envelope.payload as AgentHeartbeatPayload;
        this.patch({
          lastHeartbeatAt: envelope.sentAt,
          agents: this.snapshot.agents.map((agent) =>
            agent.agentId === agentId
              ? { ...agent, state: "connected", latencyMs, lastHeartbeatAt: envelope.sentAt }
              : agent,
          ),
        });
        break;
      }
      case "agent.disconnected": {
        this.patch({
          agents: this.snapshot.agents.map((agent) => ({
            ...agent,
            state: "disconnected",
          })),
        });
        break;
      }
      // A command was issued after an approved RiskDecision (Phase 09 bridge).
      case "execution.command.place_order": {
        const { command } = envelope.payload as PlaceOrderCommandPayload;
        // Idempotent re-registration (the single retry re-broadcasts the same
        // commandId): never downgrade an existing lifecycle back to "sent".
        if (this.snapshot.commands[command.commandId]) {
          break;
        }
        this.patch({
          commands: {
            ...this.snapshot.commands,
            [command.commandId]: {
              commandId: command.commandId,
              signalId: command.signalId,
              riskApprovalId: command.riskApprovalId,
              symbol: command.symbol,
              side: command.side,
              volume: command.volume,
              status: "sent",
              reason: null,
              issuedAt: command.issuedAt,
              updatedAt: envelope.sentAt,
            },
          },
          signals: this.setSignalStatus(command.signalId, "commanded", null),
        });
        break;
      }
      // Agent receipt. accepted/duplicate confirm; rejected/expired terminate —
      // a rejected or expired command NEVER produces a fill.
      case "execution.command.acknowledged":
      case "execution.command.rejected": {
        const { ack } = envelope.payload as CommandAckPayload;
        const confirmed = ack.status === "accepted" || ack.status === "duplicate";
        const commandStatus = confirmed
          ? "acknowledged"
          : ack.status === "expired"
            ? "expired"
            : "rejected";
        const command = this.snapshot.commands[ack.commandId];
        this.patch({
          commands: this.setCommandStatus(ack.commandId, commandStatus, ack.reason),
          signals: command
            ? this.setSignalStatus(
                command.signalId,
                confirmed ? "acknowledged" : ack.status === "expired" ? "expired" : "rejected",
                // Confirmations keep the risk-decision text on the card;
                // only failure reasons replace it.
                confirmed ? null : ack.reason,
              )
            : this.snapshot.signals,
        });
        break;
      }
      // Observe-mode outcome: validated end-to-end, no broker order. Distinct
      // status by contract — never rendered as a fill.
      case "execution.order.simulated": {
        const { report } = envelope.payload as ExecutionReportPayload;
        const command = this.snapshot.commands[report.commandId];
        this.patch({
          executionReports: [report, ...this.snapshot.executionReports].slice(
            0,
            MAX_FEED_LENGTH,
          ),
          commands: this.setCommandStatus(report.commandId, "reported", null),
          signals: command
            ? this.setSignalStatus(command.signalId, "reported", null)
            : this.snapshot.signals,
        });
        break;
      }
      case "execution.order.filled":
      case "execution.position.opened":
      case "execution.position.closed": {
        const { report } = envelope.payload as ExecutionReportPayload;
        this.patch({
          executionReports: [report, ...this.snapshot.executionReports].slice(
            0,
            MAX_FEED_LENGTH,
          ),
        });
        break;
      }
      default:
        // Unhandled event families are ignored by the Phase 01 dashboard.
        break;
    }
  }

  /** Client-side lifecycle: no ack before timeout (after the single retry). */
  markCommandFailed(commandId: string, reason: string): void {
    const command = this.snapshot.commands[commandId];
    if (!command || command.status === "acknowledged" || command.status === "reported") {
      return;
    }
    this.patch({
      commands: this.setCommandStatus(commandId, "failed", reason),
      signals: this.setSignalStatus(command.signalId, "rejected", reason),
    });
  }

  /** Client-side lifecycle: the single idempotent resend happened. */
  markCommandRetried(commandId: string): void {
    const command = this.snapshot.commands[commandId];
    if (command && command.status === "sent") {
      this.patch({ commands: this.setCommandStatus(commandId, "retried", null) });
    }
  }

  private setCommandStatus(
    commandId: string,
    status: ExecutionCommandView["status"],
    reason: string | null,
  ): Record<string, ExecutionCommandView> {
    const command = this.snapshot.commands[commandId];
    if (!command) {
      return this.snapshot.commands;
    }
    return {
      ...this.snapshot.commands,
      [commandId]: { ...command, status, reason, updatedAt: new Date().toISOString() },
    };
  }

  private setSignalStatus(
    signalId: string | null,
    status: StrategySignal["status"],
    reason: string | null,
  ): StrategySignal[] {
    if (!signalId) {
      return this.snapshot.signals;
    }
    return this.snapshot.signals.map((signal) =>
      signal.signalId === signalId
        ? { ...signal, status, riskDecision: reason ?? signal.riskDecision }
        : signal,
    );
  }

  private applyTick(symbol: string, price: number): void {
    const positions = this.snapshot.positions.map((position) => {
      if (position.symbol !== symbol) {
        return position;
      }
      const direction = position.side === "buy" ? 1 : -1;
      const move = (price - position.entryPrice) * direction;
      const risk = Math.abs(position.entryPrice - position.stopLoss);
      // XAUUSD: 1.00 price move on 1.0 lot ≈ 100 USD.
      const unrealizedPnl = Math.round(move * position.volume * 100 * 100) / 100;
      return {
        ...position,
        currentPrice: price,
        unrealizedPnl,
        rMultiple: risk > 0 ? Math.round((move / risk) * 100) / 100 : 0,
      };
    });

    const account = this.snapshot.account;
    const openPnl = positions.reduce((sum, p) => sum + p.unrealizedPnl, 0);
    this.patch({
      positions,
      account: account
        ? { ...account, equity: Math.round((account.balance + openPnl) * 100) / 100 }
        : account,
    });
  }

  private patch(partial: Partial<CockpitSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...partial };
    for (const listener of this.listeners) {
      listener();
    }
  }
}
