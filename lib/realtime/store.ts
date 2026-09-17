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
} from "@/lib/contracts/snapshots";
import type {
  AccountSnapshotPayload,
  AgentHeartbeatPayload,
  CalendarUpdatedPayload,
  ExecutionReportPayload,
  LockoutViolatedPayload,
  MarketContextUpdatedPayload,
  MarketTickPayload,
  PositionsSnapshotPayload,
  RiskLockoutAcknowledgedPayload,
  RiskLockoutEnabledPayload,
  RiskStateUpdatedPayload,
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
  agents: AgentStatus[];
  executionReports: ExecutionReport[];
  pnlCalendar: PnlCalendarDay[];
  alerts: CockpitAlert[];
  lastHeartbeatAt: string | null;
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
  /**
   * T02c: live facts of a position opened while a lockout was active,
   * Gateway-detected — see LockoutViolatedPayload. Undismissed until the
   * trader clears each one locally (dismissLockoutViolation); this is a
   * live notice, not the audit trail (T07/`/journal` already has that).
   */
  lockoutViolations: LockoutViolatedPayload[];
}

export const EMPTY_COCKPIT_SNAPSHOT: CockpitSnapshot = {
  connection: "connecting",
  environment: "mock",
  account: null,
  positions: [],
  risk: null,
  marketContext: null,
  agents: [],
  executionReports: [],
  pnlCalendar: [],
  alerts: [],
  lastHeartbeatAt: null,
  activeLockout: null,
  acknowledgedLockoutIds: [],
  upcomingReleases: null,
  lockoutViolations: [],
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
      case "risk.state.updated": {
        const { risk } = envelope.payload as RiskStateUpdatedPayload;
        this.patch({ risk });
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
      // T02c: Gateway-detected live — append, don't replace; dismissed
      // independently via dismissLockoutViolation (local, not another event).
      case "journal.lockout_violated": {
        const violation = envelope.payload as LockoutViolatedPayload;
        this.patch({
          lockoutViolations: [violation, ...this.snapshot.lockoutViolations].slice(
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
      // Observe-mode outcome: validated end-to-end, no broker order. Distinct
      // status by contract — never rendered as a fill. Real EA-05 traffic
      // lands here (Mt5AgentServer -> ExecutionOrderSimulated) as much as
      // anything else that ever reaches this event type.
      case "execution.order.simulated": {
        const { report } = envelope.payload as ExecutionReportPayload;
        this.patch({
          executionReports: [report, ...this.snapshot.executionReports].slice(
            0,
            MAX_FEED_LENGTH,
          ),
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

  /** T02c: local-only — the underlying fact is already durably in
   *  position_opens/risk_lockouts (T07/`/journal` reads it from there); this
   *  just clears the live notice from this tab. */
  dismissLockoutViolation(brokerPositionId: string): void {
    this.patch({
      lockoutViolations: this.snapshot.lockoutViolations.filter(
        (violation) => violation.brokerPositionId !== brokerPositionId,
      ),
    });
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
