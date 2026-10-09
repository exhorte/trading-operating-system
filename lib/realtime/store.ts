/**
 * The cockpit's state: what the core last told it, and nothing computed.
 *
 * The core is the only place a trading fact is decided (risk, lockouts, the state of a command, the session…). This store keeps
 * the last answer — the `system.snapshot` frame, then the events that move it — and offers it to the screens as a read model
 * of the **active account**. It never derives a rule: "locked" is the lockout the core reports, "armed" is its verdict, an
 * order's state is the state it holds. What it does decide is only how to *show* things (which link is up, whether to
 * distrust what is on screen).
 *
 * Two kinds of events:
 *   - **self-contained** ones are applied here (a position list, a risk status, a calendar);
 *   - the others only say *something changed* (a command moved, the autonomy mode moved, an account was connected). Patching the
 *     state they describe would copy the core's logic into the browser, so the store hands back an *effect* — "read it again",
 *     "ask for a fresh snapshot" — and the controller (`controller.ts`) does the reading.
 *
 * `apply` is pure bookkeeping: the same frames in the same order always give the same state. Nothing here knows about sockets,
 * timers or React, which is what lets the reducers be tested with plain objects.
 */

import type {
  Account,
  AccountSnapshot,
  AccountState,
  AgentStatus,
  AutonomyOverview,
  CalendarSnapshot,
  CockpitEvent,
  Environment,
  EventPayloads,
  ExecutionCommand,
  HealthDigest,
  Position,
  RiskStatus,
  UpcomingRelease,
} from "@/lib/api/generated";

/**
 * The link between the browser and the core, as the trader should read it. `degraded` is a link that is up to a core that says
 * it is unwell (a finding of high or critical severity): the figures arrive, but not all of them can be trusted.
 */
export type ConnectionState = "connecting" | "connected" | "reconnecting" | "stale" | "degraded" | "disconnected";

export type LinkState = Exclude<ConnectionState, "degraded">;

/** The lock the core holds on the account — what an acknowledgement has to name. `until === null`: only a person lifts it. */
export interface LockoutView {
  lockoutId: string;
  reason: string;
  until: string | null;
}

/** A position that opened while a lockout was in force — a live notice, dismissed locally; the record is the journal's. */
export type LockoutViolation = EventPayloads["risk.lockout_violated"];

/** The execution agent's last heartbeat, as this tab received it. */
export interface AgentPulse {
  latencyMs: number;
  receivedAt: string;
}

/** What the screens read. Everything about "the account" is the **active** account's. */
export interface CockpitSnapshot {
  // ---- the link
  connection: ConnectionState;
  /** Why the link is not `connected`, in words the trader can act on — or null. */
  connectionIssue: string | null;
  // ---- the core
  version: string | null;
  health: HealthDigest | null;
  autonomy: AutonomyOverview | null;
  /** The registry: every account, with its connection status. */
  accounts: Account[];
  activeAccountId: string | null;
  /** The FRED calendar. `null` is *unknown* (never synced), which the news gate treats as closed — never as an empty calendar. */
  upcomingReleases: UpcomingRelease[] | null;
  calendarSyncedAt: string | null;
  // ---- the active account
  /** Its registry entry, or null when none is active. */
  registered: Account | null;
  environment: Environment | null;
  /** MT5's account window — null until the account is connected and read. */
  account: AccountSnapshot | null;
  positions: Position[];
  risk: RiskStatus | null;
  /** The symbols the core watches for this account (what the broker quotes it), in the order it lists them. */
  watchlist: string[];
  /** The lock the core holds, read from the risk status; null when clear. */
  activeLockout: LockoutView | null;
  /** The execution agent attached to the account's terminal, or null. It is the *only* order path, and it is not the reader. */
  agent: AgentStatus | null;
  executionAgentConnected: boolean;
  agentPulse: AgentPulse | null;
  /** The most recent commands, newest first. */
  commands: ExecutionCommand[];
  lockoutViolations: LockoutViolation[];
  /** Per symbol, when a bar last closed — a screen that depends on the bars re-reads when it changes. */
  candleClosedAt: Record<string, string>;
}

/** What `apply` asks the controller to do. */
export type Effect =
  | { kind: "resync" }
  | { kind: "refresh-commands"; accountId: string }
  | { kind: "refresh-autonomy" };

interface Core {
  link: LinkState;
  linkIssue: string | null;
  version: string | null;
  health: HealthDigest | null;
  autonomy: AutonomyOverview | null;
  accounts: Account[];
  activeAccountId: string | null;
  calendar: CalendarSnapshot | null;
  states: Record<string, AccountState>;
  pulses: Record<string, AgentPulse>;
  violations: LockoutViolation[];
  candleClosedAt: Record<string, string>;
}

const EMPTY_CORE: Core = {
  link: "connecting",
  linkIssue: null,
  version: null,
  health: null,
  autonomy: null,
  accounts: [],
  activeAccountId: null,
  calendar: null,
  states: {},
  pulses: {},
  violations: [],
  candleClosedAt: {},
};

const MAX_FEED_LENGTH = 20;

// ----------------------------------------------------------------------------------------------------- the read model

function lockoutOf(risk: RiskStatus | null): LockoutView | null {
  if (risk === null || risk.lockoutId === null) {
    return null;
  }
  return { lockoutId: risk.lockoutId, reason: risk.lockoutReason ?? "", until: risk.lockoutUntil };
}

function connectionOf(core: Core): ConnectionState {
  const bad = core.health?.status === "high" || core.health?.status === "critical";
  return core.link === "connected" && bad ? "degraded" : core.link;
}

/** The registry entry of the account an agent serves: the agent states its MT5 login, the registry knows which account that is. */
function accountOfLogin(accounts: Account[], login: string): Account | undefined {
  return accounts.find((account) => String(account.login) === login);
}

export function derive(core: Core): CockpitSnapshot {
  const id = core.activeAccountId;
  const state = id === null ? undefined : core.states[id];
  const registered = id === null ? null : (core.accounts.find((account) => account.id === id) ?? null);
  const risk = state?.risk ?? null;
  const agent = state?.agent ?? null;
  return {
    connection: connectionOf(core),
    connectionIssue: core.linkIssue,
    version: core.version,
    health: core.health,
    autonomy: core.autonomy,
    accounts: core.accounts,
    activeAccountId: id,
    upcomingReleases: core.calendar === null ? null : core.calendar.releases,
    calendarSyncedAt: core.calendar?.syncedAt ?? null,
    registered,
    environment: registered?.environment ?? null,
    account: state?.snapshot ?? null,
    positions: state?.positions ?? NO_POSITIONS,
    watchlist: state === undefined ? NO_SYMBOLS : state.quotes.map((tick) => tick.symbol),
    risk,
    activeLockout: lockoutOf(risk),
    agent,
    executionAgentConnected: agent !== null,
    agentPulse: agent === null ? null : (core.pulses[agent.agentId] ?? null),
    commands: state?.commands ?? NO_COMMANDS,
    lockoutViolations: core.violations,
    candleClosedAt: core.candleClosedAt,
  };
}

const NO_POSITIONS: Position[] = [];
const NO_SYMBOLS: string[] = [];
const NO_COMMANDS: ExecutionCommand[] = [];

export const EMPTY_COCKPIT_SNAPSHOT: CockpitSnapshot = derive(EMPTY_CORE);

// ----------------------------------------------------------------------------------------------------- the reducer

interface Reduction {
  core: Core;
  effects: Effect[];
}

const same = (core: Core): Reduction => ({ core, effects: [] });

function inState(core: Core, accountId: string | null, patch: Partial<AccountState>): Reduction {
  // An event for an account the snapshot did not list (connected a moment ago): the fresh snapshot will carry it.
  const known = accountId === null ? undefined : core.states[accountId];
  if (accountId === null || known === undefined) {
    return same(core);
  }
  return same({ ...core, states: { ...core.states, [accountId]: { ...known, ...patch } } });
}

function withAgent(core: Core, login: string, agent: AgentStatus | null): Reduction {
  const account = accountOfLogin(core.accounts, login);
  return account === undefined ? same(core) : inState(core, account.id, { agent });
}

function reduce(core: Core, frame: CockpitEvent): Reduction {
  switch (frame.type) {
    case "system.snapshot": {
      const snapshot = frame.payload;
      return same({
        ...core,
        version: snapshot.version,
        accounts: snapshot.accounts,
        activeAccountId: snapshot.activeAccountId,
        autonomy: snapshot.autonomy,
        health: snapshot.health,
        calendar: snapshot.calendar,
        states: snapshot.accountStates,
      });
    }
    case "system.health_changed":
      return same({
        ...core,
        health: { status: frame.payload.status, findings: frame.payload.findings, checkedAt: frame.occurredAt },
      });
    case "market.calendar_updated":
      return same({ ...core, calendar: { releases: frame.payload.releases, syncedAt: frame.payload.syncedAt } });
    case "market.candle_closed": {
      const { symbol, openTime } = frame.payload.candle;
      return same({ ...core, candleClosedAt: { ...core.candleClosedAt, [symbol]: openTime } });
    }
    case "account.snapshot":
      return inState(core, frame.accountId, { snapshot: frame.payload.snapshot });
    case "positions.snapshot":
      return inState(core, frame.accountId, { positions: frame.payload.positions });
    case "risk.state_updated":
      return inState(core, frame.accountId, { risk: frame.payload.risk });
    case "risk.lockout_violated": {
      const violation = frame.payload;
      const others = core.violations.filter((v) => v.brokerPositionId !== violation.brokerPositionId);
      return same({ ...core, violations: [violation, ...others].slice(0, MAX_FEED_LENGTH) });
    }
    case "agent.connected":
    case "agent.status_changed":
      return withAgent(core, frame.payload.status.accountLogin, frame.payload.status);
    case "agent.disconnected":
      return withAgent(core, frame.payload.agentLogin, null);
    case "agent.heartbeat": {
      const { agentId, latencyMs } = frame.payload;
      return same({ ...core, pulses: { ...core.pulses, [agentId]: { latencyMs, receivedAt: frame.occurredAt } } });
    }
    case "execution.command_created": {
      // The one execution event that carries the whole command: show it at once, the others re-read the list.
      const command = frame.payload.command;
      const known = frame.accountId === null ? undefined : core.states[frame.accountId];
      if (known === undefined) {
        return same(core);
      }
      const rest = known.commands.filter((c) => c.request.commandId !== command.request.commandId);
      return inState(core, frame.accountId, { commands: [command, ...rest].slice(0, MAX_FEED_LENGTH) });
    }
    case "execution.command_sent":
    case "execution.acknowledged":
    case "execution.reported":
    case "execution.failed":
    case "execution.rejected":
    case "execution.unknown":
    case "execution.reconciled":
      return frame.accountId === null
        ? same(core)
        : { core, effects: [{ kind: "refresh-commands", accountId: frame.accountId }] };
    case "autonomy.armed":
    case "autonomy.disarmed":
    case "autonomy.halted":
    case "autonomy.mode_changed":
    case "autonomy.readiness_changed":
      return { core, effects: [{ kind: "refresh-autonomy" }] };
    // The registry and the connections: the snapshot is the authority on who is connected and active, so ask for it.
    case "account.created":
    case "account.updated":
    case "account.archived":
    case "account.connected":
    case "account.disconnected":
    case "account.error":
    case "account.trading_toggled":
    case "account.active_changed":
    case "account.rules_changed":
      return { core, effects: [{ kind: "resync" }] };
    default:
      // Ticks (no screen draws them), heartbeats, strategy and reconciliation notices, incidents…: nothing to keep. A screen
      // that wants one subscribes to the event stream (`onEvent`) and re-reads what it shows.
      return same(core);
  }
}

// ----------------------------------------------------------------------------------------------------- the store

export class CockpitStore {
  private core: Core = EMPTY_CORE;

  private view: CockpitSnapshot = EMPTY_COCKPIT_SNAPSHOT;

  private listeners = new Set<() => void>();

  private eventListeners = new Set<(frame: CockpitEvent) => void>();

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = (): CockpitSnapshot => this.view;

  /** Every frame, after it has been applied — for a screen that re-reads something when a kind of event arrives. */
  onEvent = (listener: (frame: CockpitEvent) => void): (() => void) => {
    this.eventListeners.add(listener);
    return () => {
      this.eventListeners.delete(listener);
    };
  };

  /** The link's state, from the socket. */
  setLink(link: LinkState, issue: string | null): void {
    if (this.core.link === link && this.core.linkIssue === issue) {
      return;
    }
    this.commit({ ...this.core, link, linkIssue: issue });
  }

  /** Apply one frame. Returns what the controller has to do next. */
  apply(frame: CockpitEvent): Effect[] {
    const { core, effects } = reduce(this.core, frame);
    this.commit(core);
    for (const listener of this.eventListeners) {
      listener(frame);
    }
    return effects;
  }

  /** The commands of an account, re-read (the answer to a `refresh-commands` effect). */
  setCommands(accountId: string, commands: ExecutionCommand[]): void {
    this.commit(inState(this.core, accountId, { commands: commands.slice(0, MAX_FEED_LENGTH) }).core);
  }

  setAutonomy(autonomy: AutonomyOverview): void {
    this.commit({ ...this.core, autonomy });
  }

  /** T02c: local only — the fact itself is already in the journal; this clears the live notice from this tab. */
  dismissLockoutViolation(brokerPositionId: string): void {
    this.commit({ ...this.core, violations: this.core.violations.filter((v) => v.brokerPositionId !== brokerPositionId) });
  }

  private commit(core: Core): void {
    if (core === this.core) {
      return;
    }
    this.core = core;
    this.view = derive(core);
    for (const listener of this.listeners) {
      listener();
    }
  }
}
