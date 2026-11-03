/**
 * Typed builders for the frames and models the store tests feed it. They are typed against the generated contract on purpose:
 * when the core changes a model, this file stops compiling before a test can pass on a shape the core no longer sends.
 */

import type {
  Account,
  AccountSnapshot,
  AccountState,
  AgentStatus,
  AutonomyOverview,
  CockpitEvent,
  EventPayloads,
  EventType,
  ExecutionCommand,
  HealthDigest,
  Position,
  RiskStatus,
} from "@/lib/api/generated";

export const T0 = "2026-10-09T10:00:00Z";

export function account(overrides: Partial<Account> = {}): Account {
  return {
    id: "exness-1000001",
    name: "Exness démo",
    provider: "EXNESS",
    platform: "MT5",
    accountType: "DIRECT",
    login: 1000001,
    server: "Exness-MT5Trial",
    currency: "USD",
    environment: "DEMO",
    terminalPath: null,
    symbolSuffix: "m",
    status: "CONNECTED",
    statusDetail: null,
    tradingEnabled: true,
    riskProfile: {
      maxRiskPerTradePercent: 0.5,
      dynamic: {
        grid: [
          { levelPercent: 0, riskPercent: 0.5 },
          { levelPercent: -1, riskPercent: null },
        ],
        absoluteLossTriggerAmount: 200,
        absoluteLossRiskCapPercent: 1,
      },
      maxOpenRiskPercent: 1,
      maxCorrelatedRiskPercent: 1,
      maxTradesPerDay: 3,
      maxConsecutiveLosses: 2,
      consecutiveLossPauseMinutes: 30,
      drawdown: { dailyLossLimitPercent: 5, weeklyLossLimitPercent: 10, maxDrawdownLimitPercent: 10, referenceBalance: 10000 },
      news: { blackoutMinutes: 15, calendarMaxAgeHours: 48 },
      positions: { maxOpenPositions: 2, maxVolumePerOrder: null },
      configured: true,
    },
    tradingRules: {
      allowedSymbols: null,
      tradingWindows: [],
      challenge: null,
      minTradingDays: null,
      profitTargetPercent: null,
    },
    executionProfile: {
      maxMode: "OBSERVE",
      limits: {
        maxSlippagePoints: 10,
        commandTtlSeconds: 60,
        commissionPerLotRoundTrip: 0,
        costThreshold: 0.25,
        maxSpreadBySymbol: {},
      },
    },
    createdAt: T0,
    ...overrides,
  };
}

export function snapshot(overrides: Partial<AccountSnapshot> = {}): AccountSnapshot {
  return {
    accountId: "exness-1000001",
    label: "Exness démo",
    broker: "Exness Technologies Ltd",
    currency: "USD",
    balance: 10000,
    equity: 10050,
    dailyPnl: 50,
    dailyDrawdownPercent: 0,
    totalDrawdownPercent: 0,
    openRiskPercent: 0.5,
    margin: null,
    freeMargin: null,
    marginLevel: null,
    server: "Exness-MT5Trial",
    tradeMode: "demo",
    leverage: 500,
    marginMode: "hedging",
    fifoClose: false,
    tradeAllowed: true,
    tradeExpert: true,
    observedAt: T0,
    ...overrides,
  };
}

export function risk(overrides: Partial<RiskStatus> = {}): RiskStatus {
  return {
    state: "normal",
    dailyLossLimitPercent: 5,
    dailyLossUsedPercent: 0.4,
    weeklyLossLimitPercent: 10,
    weeklyLossUsedPercent: 0,
    performancePercent: 0,
    allowance: {
      status: "allowed",
      riskPercent: 1,
      performancePercent: 0,
      tierLevelPercent: 0,
      gridPercent: 1,
      bindingCap: "grid",
      caps: [],
      reason: null,
      detail: "1 % (grid)",
    },
    maxDrawdownLimitPercent: 10,
    maxDrawdownUsedPercent: 0.4,
    openRiskLimitPercent: 1,
    openRiskPercent: 0.5,
    correlatedExposureLimitPercent: 1,
    correlatedExposurePercent: 0.5,
    maxTradesPerDay: 3,
    tradesToday: 1,
    consecutiveLosses: 0,
    lockoutReason: null,
    lockoutUntil: null,
    lockoutId: null,
    gates: [{ gateId: "gate-daily-loss", label: "Perte du jour", state: "open", detail: "0.4 % / 5 %" }],
    evaluatedAt: T0,
    ...overrides,
  };
}

export function position(overrides: Partial<Position> = {}): Position {
  return {
    positionId: "p1",
    accountId: "exness-1000001",
    symbol: "EURUSDm",
    side: "buy",
    volume: 0.1,
    entryPrice: 1.085,
    currentPrice: 1.0862,
    stopLoss: 1.083,
    takeProfit: 1.09,
    unrealizedPnl: 12,
    rMultiple: 0.6,
    magicNumber: null,
    comment: "",
    strategyId: "S01",
    openedAt: T0,
    ...overrides,
  };
}

export function agent(overrides: Partial<AgentStatus> = {}): AgentStatus {
  return {
    accountLogin: "1000001",
    agentId: "mt5-execution-agent-4242",
    agentVersion: "1.0.0",
    buildId: "b1",
    mode: "observe",
    modeCeiling: "observe",
    identity: "ok",
    expectedAccountId: "1000001",
    broker: "Exness",
    server: "Exness-MT5Trial",
    currency: "USD",
    tradeMode: "demo",
    marginMode: "hedging",
    fifoClose: false,
    leverage: 500,
    terminalTradeAllowed: true,
    expertTradeAllowed: true,
    accountTradeExpert: true,
    accountTradeAllowed: true,
    tradable: true,
    closable: true,
    halted: false,
    attachedExperts: [],
    capabilities: [],
    coreSilentMs: 100,
    lastHeartbeatMs: 100,
    ...overrides,
  };
}

export function command(commandId: string, overrides: Partial<ExecutionCommand> = {}): ExecutionCommand {
  return {
    request: {
      commandId,
      accountId: "exness-1000001",
      kind: "OPEN",
      symbol: "EURUSDm",
      side: "buy",
      orderType: "market",
      volume: 0.1,
      price: null,
      stopLoss: 1.083,
      takeProfit: 1.09,
      strategyId: "S01",
      strategyVersion: "1",
      riskDecisionId: "d1",
      positionId: null,
      orderId: null,
      expiresAt: null,
    },
    fingerprint: "f",
    state: "PENDING",
    route: "automatic",
    mode: "OBSERVE",
    createdAt: T0,
    expiresAt: T0,
    sentAt: null,
    acknowledgedAt: null,
    completedAt: null,
    attempts: 0,
    detail: "",
    rejectCode: null,
    brokerOrderId: null,
    brokerPositionId: null,
    filledVolume: null,
    averagePrice: null,
    brokerRetcode: null,
    ...overrides,
  };
}

export function accountState(overrides: Partial<AccountState> = {}): AccountState {
  return {
    snapshot: snapshot(),
    positions: [],
    orders: [],
    quotes: [],
    risk: risk(),
    agent: null,
    commands: [],
    ...overrides,
  };
}

export function autonomy(overrides: Partial<AutonomyOverview> = {}): AutonomyOverview {
  return {
    state: { mode: "OBSERVE", since: T0, leaseUntil: null, haltedReason: null, lastTransition: null },
    ceiling: "OBSERVE",
    effectiveMode: "OBSERVE",
    activeAccountId: "exness-1000001",
    readiness: null,
    ...overrides,
  };
}

export function health(overrides: Partial<HealthDigest> = {}): HealthDigest {
  return { status: "ok", findings: [], checkedAt: T0, ...overrides };
}

let counter = 0;

/** A frame of any type, with the envelope the core puts around it. */
export function frame<T extends EventType>(
  type: T,
  payload: EventPayloads[T],
  envelope: { accountId?: string | null; occurredAt?: string } = {},
): CockpitEvent {
  counter += 1;
  return {
    type,
    payload,
    id: `evt-${counter}`,
    occurredAt: envelope.occurredAt ?? T0,
    accountId: envelope.accountId === undefined ? null : envelope.accountId,
    correlationId: null,
  } as CockpitEvent;
}

/** The first frame of a connection: one connected account, the lot. */
export function snapshotFrame(overrides: Partial<EventPayloads["system.snapshot"]> = {}): CockpitEvent {
  const a = account();
  return frame("system.snapshot", {
    serverTime: T0,
    version: "0.1.0",
    activeAccountId: a.id,
    accounts: [a],
    autonomy: autonomy(),
    health: health(),
    calendar: { releases: [], syncedAt: T0 },
    accountStates: { [a.id]: accountState() },
    ...overrides,
  });
}
