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
  ExecutionReport,
  MarketContext,
  PnlCalendarDay,
  Position,
  RiskStatus,
  StrategySignal,
} from "@/lib/contracts/snapshots";
import type {
  AccountSnapshotPayload,
  AgentHeartbeatPayload,
  ExecutionReportPayload,
  MarketContextUpdatedPayload,
  MarketTickPayload,
  RiskStateUpdatedPayload,
  SignalCreatedPayload,
  SignalUpdatedPayload,
} from "@/lib/contracts/events";

export interface CockpitSnapshot {
  connection: ConnectionState;
  environment: Environment;
  account: AccountSummary | null;
  positions: Position[];
  risk: RiskStatus | null;
  marketContext: MarketContext | null;
  signals: StrategySignal[];
  agents: AgentStatus[];
  executionReports: ExecutionReport[];
  pnlCalendar: PnlCalendarDay[];
  alerts: CockpitAlert[];
  lastHeartbeatAt: string | null;
}

export const EMPTY_COCKPIT_SNAPSHOT: CockpitSnapshot = {
  connection: "connecting",
  environment: "mock",
  account: null,
  positions: [],
  risk: null,
  marketContext: null,
  signals: [],
  agents: [],
  executionReports: [],
  pnlCalendar: [],
  alerts: [],
  lastHeartbeatAt: null,
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
      case "execution.order.filled":
      case "execution.command.acknowledged":
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
