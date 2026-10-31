import { describe, expect, it, vi } from "vitest";
import { CockpitStore, EMPTY_COCKPIT_SNAPSHOT } from "./store";
import {
  T0,
  account,
  accountState,
  agent,
  autonomy,
  command,
  frame,
  health,
  position,
  risk,
  snapshot,
  snapshotFrame,
} from "./test-fixtures";

const ID = "exness-1000001";

function connected(overrides: Parameters<typeof snapshotFrame>[0] = {}): CockpitStore {
  const store = new CockpitStore();
  store.setLink("connected", null);
  store.apply(snapshotFrame(overrides));
  return store;
}

describe("before anything has arrived", () => {
  it("fails closed: no account, no risk, an unknown calendar, no agent", () => {
    const s = EMPTY_COCKPIT_SNAPSHOT;
    expect(s.connection).toBe("connecting");
    expect(s.account).toBeNull();
    expect(s.risk).toBeNull();
    expect(s.activeLockout).toBeNull();
    expect(s.upcomingReleases).toBeNull(); // unknown, never "an empty calendar" — the news gate reads it as closed
    expect(s.executionAgentConnected).toBe(false);
    expect(s.positions).toEqual([]);
  });
});

describe("system.snapshot", () => {
  it("is the whole state: the active account's view comes from it", () => {
    const store = connected({
      accountStates: { [ID]: accountState({ positions: [position()], commands: [command("c1")] }) },
    });
    const s = store.getSnapshot();
    expect(s.activeAccountId).toBe(ID);
    expect(s.registered?.name).toBe("Exness démo");
    expect(s.environment).toBe("DEMO");
    expect(s.account?.equity).toBe(10050);
    expect(s.positions.map((p) => p.positionId)).toEqual(["p1"]);
    expect(s.commands.map((c) => c.request.commandId)).toEqual(["c1"]);
    expect(s.autonomy?.effectiveMode).toBe("OBSERVE");
    expect(s.version).toBe("0.1.0");
    expect(s.upcomingReleases).toEqual([]);
  });

  it("replaces what was there: a resynchronisation forgets what the core no longer holds", () => {
    const store = connected({ accountStates: { [ID]: accountState({ positions: [position()] }) } });
    store.apply(snapshotFrame({ accountStates: { [ID]: accountState({ positions: [] }) } }));
    expect(store.getSnapshot().positions).toEqual([]);
    store.apply(snapshotFrame({ activeAccountId: null, accountStates: {} }));
    const s = store.getSnapshot();
    expect(s.registered).toBeNull();
    expect(s.account).toBeNull();
    expect(s.risk).toBeNull();
  });

  it("lists the symbols the core watches for the account", () => {
    const tick = (symbol: string) => ({ symbol, bid: 1, ask: 1.1, last: null, time: T0 });
    const store = connected({
      accountStates: { [ID]: accountState({ quotes: [tick("EURUSDm"), tick("XAUUSDm")] }) },
    });
    expect(store.getSnapshot().watchlist).toEqual(["EURUSDm", "XAUUSDm"]);
    expect(connected().getSnapshot().watchlist).toEqual([]);
  });

  it("shows no account state for an active account that is not connected", () => {
    const store = connected({ accountStates: {} }); // listed and active, but no terminal behind it
    const s = store.getSnapshot();
    expect(s.registered?.id).toBe(ID);
    expect(s.account).toBeNull();
    expect(s.positions).toEqual([]);
  });

  it("keeps the live notices a resync would otherwise erase", () => {
    const store = connected();
    store.apply(
      frame("risk.lockout_violated", {
        brokerPositionId: "p9",
        symbol: "EURUSDm",
        side: "buy",
        lockoutId: "l1",
        lockoutReason: "Kill switch manuel",
        openedAt: T0,
      }),
    );
    store.apply(snapshotFrame());
    expect(store.getSnapshot().lockoutViolations).toHaveLength(1);
  });
});

describe("the link", () => {
  it("is the socket's state, and a core that says it is unwell downgrades a live link to degraded", () => {
    const store = connected();
    expect(store.getSnapshot().connection).toBe("connected");
    store.apply(frame("system.health_changed", { status: "high", findings: [] }));
    expect(store.getSnapshot().connection).toBe("degraded");
    store.apply(frame("system.health_changed", { status: "medium", findings: [] }));
    expect(store.getSnapshot().connection).toBe("connected"); // medium is worth showing, not distrusting
    store.apply(frame("system.health_changed", { status: "critical", findings: [] }));
    store.setLink("stale", "plus de battement");
    expect(store.getSnapshot().connection).toBe("stale"); // a dead link outranks the core's opinion of itself
    expect(store.getSnapshot().connectionIssue).toBe("plus de battement");
  });

  it("does not notify when nothing changed", () => {
    const store = connected();
    const listener = vi.fn();
    store.subscribe(listener);
    store.setLink("connected", null);
    store.apply(frame("system.heartbeat", { seq: 1, uptimeSeconds: 2 }));
    store.apply(frame("market.tick", { tick: { symbol: "EURUSDm", bid: 1, ask: 1.1, last: null, time: T0 } }));
    expect(listener).not.toHaveBeenCalled();
    store.setLink("reconnecting", "x");
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

describe("the active account's events", () => {
  it("replaces the position list from positions.snapshot", () => {
    const store = connected();
    store.apply(frame("positions.snapshot", { positions: [position(), position({ positionId: "p2" })] }, { accountId: ID }));
    expect(store.getSnapshot().positions.map((p) => p.positionId)).toEqual(["p1", "p2"]);
  });

  it("takes the account window and the risk status as the core sends them", () => {
    const store = connected();
    store.apply(frame("account.snapshot", { snapshot: snapshot({ equity: 9000 }) }, { accountId: ID }));
    store.apply(frame("risk.state_updated", { risk: risk({ state: "warning", dailyLossUsedPercent: 3 }) }, { accountId: ID }));
    const s = store.getSnapshot();
    expect(s.account?.equity).toBe(9000);
    expect(s.risk?.state).toBe("warning");
  });

  it("ignores an event for an account it does not hold — the fresh snapshot will carry it", () => {
    const store = connected();
    const before = store.getSnapshot();
    store.apply(frame("positions.snapshot", { positions: [position()] }, { accountId: "someone-else" }));
    store.apply(frame("positions.snapshot", { positions: [position()] }, { accountId: null }));
    expect(store.getSnapshot()).toBe(before);
  });

  it("reads the lock from the risk status — id, reason, and whether only a person can lift it", () => {
    const store = connected();
    expect(store.getSnapshot().activeLockout).toBeNull();
    store.apply(
      frame(
        "risk.state_updated",
        { risk: risk({ state: "locked", lockoutId: "l1", lockoutReason: "Kill switch manuel", lockoutUntil: null }) },
        { accountId: ID },
      ),
    );
    expect(store.getSnapshot().activeLockout).toEqual({ lockoutId: "l1", reason: "Kill switch manuel", until: null });
    store.apply(
      frame(
        "risk.state_updated",
        { risk: risk({ state: "locked", lockoutId: "l2", lockoutReason: "Pertes consécutives", lockoutUntil: "2026-10-09T10:30:00Z" }) },
        { accountId: ID },
      ),
    );
    expect(store.getSnapshot().activeLockout?.until).toBe("2026-10-09T10:30:00Z"); // a pause: it ends by itself
    store.apply(frame("risk.state_updated", { risk: risk() }, { accountId: ID }));
    expect(store.getSnapshot().activeLockout).toBeNull();
  });

  it("a locked state without a ledger row is a lock the screen cannot acknowledge — it reports none", () => {
    const store = connected();
    store.apply(frame("risk.state_updated", { risk: risk({ state: "locked", lockoutId: null }) }, { accountId: ID }));
    expect(store.getSnapshot().risk?.state).toBe("locked");
    expect(store.getSnapshot().activeLockout).toBeNull();
  });
});

describe("the execution agent", () => {
  it("is attached to the account whose login it states", () => {
    const store = connected();
    expect(store.getSnapshot().executionAgentConnected).toBe(false);
    store.apply(frame("agent.connected", { status: agent() }));
    const s = store.getSnapshot();
    expect(s.executionAgentConnected).toBe(true);
    expect(s.agent?.agentId).toBe("mt5-execution-agent-4242");
    store.apply(frame("agent.status_changed", { status: agent({ halted: true }) }));
    expect(store.getSnapshot().agent?.halted).toBe(true);
    store.apply(frame("agent.disconnected", { agentLogin: "1000001" }));
    expect(store.getSnapshot().executionAgentConnected).toBe(false);
  });

  it("ignores an agent whose login is no registered account's", () => {
    const store = connected();
    const before = store.getSnapshot();
    store.apply(frame("agent.connected", { status: agent({ accountLogin: "999" }) }));
    expect(store.getSnapshot()).toBe(before);
  });

  it("keeps the latest heartbeat per agent", () => {
    const store = connected({ accountStates: { [ID]: accountState({ agent: agent() }) } });
    store.apply(frame("agent.heartbeat", { agentId: "mt5-execution-agent-4242", latencyMs: 12 }, { occurredAt: "2026-10-09T10:00:05Z" }));
    expect(store.getSnapshot().agentPulse).toEqual({ latencyMs: 12, receivedAt: "2026-10-09T10:00:05Z" });
    store.apply(frame("agent.heartbeat", { agentId: "another", latencyMs: 99 }));
    expect(store.getSnapshot().agentPulse?.latencyMs).toBe(12);
  });
});

describe("commands", () => {
  it("shows a created command at once, newest first, once", () => {
    const store = connected({ accountStates: { [ID]: accountState({ commands: [command("c1")] }) } });
    store.apply(frame("execution.command_created", { command: command("c2") }, { accountId: ID }));
    store.apply(frame("execution.command_created", { command: command("c2", { state: "SENT" }) }, { accountId: ID }));
    const commands = store.getSnapshot().commands;
    expect(commands.map((c) => c.request.commandId)).toEqual(["c2", "c1"]);
    expect(commands[0].state).toBe("SENT");
  });

  it("asks for the list again on any other execution event rather than replaying the state machine", () => {
    const store = connected();
    for (const type of [
      "execution.command_sent",
      "execution.acknowledged",
      "execution.reported",
      "execution.failed",
      "execution.rejected",
      "execution.unknown",
      "execution.reconciled",
    ] as const) {
      const effects = store.apply(frame(type, { commandId: "c1" } as never, { accountId: ID }));
      expect(effects).toEqual([{ kind: "refresh-commands", accountId: ID }]);
    }
    expect(store.apply(frame("execution.rejected", { commandId: "c1" } as never))).toEqual([]); // no account: nothing to re-read
  });

  it("takes the re-read list as it is, capped", () => {
    const store = connected();
    store.setCommands(ID, Array.from({ length: 30 }, (_, i) => command(`c${i}`)));
    expect(store.getSnapshot().commands).toHaveLength(20);
    store.setCommands("someone-else", [command("x")]);
    expect(store.getSnapshot().commands).toHaveLength(20);
  });
});

describe("the other events", () => {
  it("asks for the autonomy overview again when the mode moves", () => {
    const store = connected();
    expect(store.apply(frame("autonomy.mode_changed", { previous: "OFF", current: "OBSERVE", reason: "x", leaseUntil: null }))).toEqual([
      { kind: "refresh-autonomy" },
    ]);
    store.setAutonomy(autonomy({ effectiveMode: "HALTED" }));
    expect(store.getSnapshot().autonomy?.effectiveMode).toBe("HALTED");
  });

  it("asks for a fresh snapshot when the registry or a connection moves", () => {
    const store = connected();
    for (const effect of [
      store.apply(frame("account.connected", { server: "s", currency: "USD", environment: "DEMO" }, { accountId: ID })),
      store.apply(frame("account.disconnected", { reason: "user" }, { accountId: ID })),
      store.apply(frame("account.active_changed", { previous: null, current: ID })),
      store.apply(frame("account.rules_changed", { versionId: "v", deferred: false, reasons: [] }, { accountId: ID })),
    ]) {
      expect(effect).toEqual([{ kind: "resync" }]);
    }
  });

  it("keeps the calendar the core publishes, and the difference between 'empty' and 'never synced'", () => {
    const store = connected({ calendar: { releases: null, syncedAt: null } });
    expect(store.getSnapshot().upcomingReleases).toBeNull();
    store.apply(
      frame("market.calendar_updated", {
        releases: [{ releaseId: 1, label: "CPI", scheduledAt: "2026-10-10T12:30:00Z" }],
        syncedAt: T0,
      }),
    );
    expect(store.getSnapshot().upcomingReleases).toHaveLength(1);
    expect(store.getSnapshot().calendarSyncedAt).toBe(T0);
  });

  it("notes when a bar closed, per symbol, for the screens that depend on bars", () => {
    const store = connected();
    store.apply(
      frame("market.candle_closed", {
        candle: { symbol: "EURUSDm", timeframe: "M1", openTime: T0, open: 1, high: 1, low: 1, close: 1, volume: 1, closed: true },
      }),
    );
    expect(store.getSnapshot().candleClosedAt).toEqual({ EURUSDm: T0 });
  });

  it("lists a lockout violation once per position and lets the trader dismiss it locally", () => {
    const store = connected();
    const violation = {
      brokerPositionId: "p9",
      symbol: "EURUSDm",
      side: "buy" as const,
      lockoutId: "l1",
      lockoutReason: "Kill switch manuel",
      openedAt: T0,
    };
    store.apply(frame("risk.lockout_violated", violation));
    store.apply(frame("risk.lockout_violated", violation));
    expect(store.getSnapshot().lockoutViolations).toHaveLength(1);
    store.dismissLockoutViolation("p9");
    expect(store.getSnapshot().lockoutViolations).toEqual([]);
  });

  it("hands every frame to the screens that listen, applied or not", () => {
    const store = connected();
    const seen: string[] = [];
    const stop = store.onEvent((f) => seen.push(f.type));
    store.apply(frame("strategy.evaluation_completed", { strategyId: "S01", symbol: "EURUSDm", outcome: "blocked", stage: null, detail: null, eventAt: T0 }));
    store.apply(frame("position.closed", { trade: { accountId: ID, brokerPositionId: "p1", symbol: "EURUSDm", side: "buy", volume: 1, realizedPnl: 1, exitPrice: 1, closedAt: T0 } }, { accountId: ID }));
    stop();
    store.apply(frame("system.heartbeat", { seq: 2, uptimeSeconds: 3 }));
    expect(seen).toEqual(["strategy.evaluation_completed", "position.closed"]);
  });
});

describe("health", () => {
  it("is the digest the core sent, then the one it publishes when it changes", () => {
    const store = connected({ health: health({ status: "ok" }) });
    expect(store.getSnapshot().health?.status).toBe("ok");
    store.apply(
      frame(
        "system.health_changed",
        {
          status: "high",
          findings: [
            { code: "mt5_silent", component: "mt5", severity: "high", detail: "x", observedAt: T0, persisting: true, accountId: ID },
          ],
        },
        { occurredAt: "2026-10-09T10:01:00Z" },
      ),
    );
    expect(store.getSnapshot().health).toMatchObject({ status: "high", checkedAt: "2026-10-09T10:01:00Z" });
    expect(store.getSnapshot().health?.findings).toHaveLength(1);
  });
});

describe("environment", () => {
  it("is the registered account's, so a simulated terminal can never read as live", () => {
    const store = connected({
      accounts: [account({ environment: "SIMULATED" })],
      accountStates: { [ID]: accountState() },
    });
    expect(store.getSnapshot().environment).toBe("SIMULATED");
    const live = connected({ accounts: [account({ environment: "LIVE" })] });
    expect(live.getSnapshot().environment).toBe("LIVE");
  });
});
