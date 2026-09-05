import { describe, expect, it } from "vitest";
import {
  lowercaseSide,
  toAccountSummary,
  toAgentStatus,
  toCandle,
  toPositions,
} from "./mt5-translate";
import type {
  Mt5AccountSnapshotMessage,
  Mt5CandleMessage,
  Mt5HelloMessage,
  Mt5PositionsSnapshotMessage,
} from "@/lib/contracts/mt5-wire";

const hello: Mt5HelloMessage = {
  version: 1,
  type: "agent.hello",
  accountId: "5099xxxx",
  time: Date.UTC(2026, 0, 5, 13, 0, 0),
  agentId: "mt5-observer-1",
  symbol: "XAUUSDm",
  broker: "Exness Technologies Ltd",
  server: "Exness-MT5Trial8",
  orderTypes: ["market"],
  minVolume: 0.01,
  maxVolume: 200,
  volumeStep: 0.01,
  fillingMode: "IOC",
  stopsLevelPoints: 0,
  mode: "observe",
  agentVersion: "0.1.0-observer",
};

describe("toAccountSummary", () => {
  it("maps real balance/equity and derives floating dailyPnl", () => {
    const msg: Mt5AccountSnapshotMessage = {
      version: 1,
      type: "account.snapshot",
      accountId: "5099xxxx",
      time: Date.now(),
      balance: 1000,
      equity: 1012.5,
      margin: 50,
      freeMargin: 962.5,
      currency: "USD",
    };
    const acc = toAccountSummary(msg, hello);
    expect(acc.balance).toBe(1000);
    expect(acc.equity).toBe(1012.5);
    expect(acc.dailyPnl).toBe(12.5);
    expect(acc.currency).toBe("USD");
    expect(acc.broker).toBe("Exness Technologies Ltd");
    // Honest zeros until a risk engine exists.
    expect(acc.dailyDrawdownPercent).toBe(0);
    expect(acc.openRiskPercent).toBe(0);
  });
});

describe("toPositions", () => {
  const msg: Mt5PositionsSnapshotMessage = {
    version: 1,
    type: "positions.snapshot",
    accountId: "5099xxxx",
    time: Date.UTC(2026, 0, 5, 13, 30, 0),
    positions: [
      {
        brokerPositionId: "pos-42",
        symbol: "XAUUSDm",
        side: "BUY",
        volume: 0.1,
        entryPrice: 3300,
        stopLoss: 3290,
        takeProfit: 3320,
        floatingPnl: 7.5,
      },
    ],
  };

  it("lowercases side, keeps real floating P&L, computes R from current price", () => {
    const [pos] = toPositions(msg, 3305);
    expect(pos.side).toBe("buy");
    expect(pos.unrealizedPnl).toBe(7.5);
    expect(pos.currentPrice).toBe(3305);
    // move +5 on risk 10 -> 0.5R
    expect(pos.rMultiple).toBe(0.5);
    expect(pos.strategyId).toBe("live-observed");
  });

  it("falls back to entry price when no tick is known yet", () => {
    const [pos] = toPositions(msg, null);
    expect(pos.currentPrice).toBe(3300);
    expect(pos.rMultiple).toBe(0);
  });
});

describe("toCandle / toAgentStatus / lowercaseSide", () => {
  it("maps a candle message to a domain Candle with ISO open time", () => {
    const msg: Mt5CandleMessage = {
      version: 1,
      type: "market.candle",
      accountId: "5099xxxx",
      time: Date.now(),
      symbol: "XAUUSDm",
      timeframe: "M15",
      openTime: Date.UTC(2026, 0, 5, 13, 0, 0),
      open: 3300,
      high: 3305,
      low: 3299,
      close: 3304,
      volume: 120,
      closed: true,
    };
    const candle = toCandle(msg);
    expect(candle.openTime).toBe("2026-01-05T13:00:00.000Z");
    expect(candle.timeframe).toBe("M15");
    expect(candle.close).toBe(3304);
  });

  it("maps hello to a connected agent status", () => {
    const agent = toAgentStatus(hello);
    expect(agent.platform).toBe("MT5");
    expect(agent.state).toBe("connected");
    expect(agent.version).toBe("0.1.0-observer");
  });

  it("lowercases sides", () => {
    expect(lowercaseSide("BUY")).toBe("buy");
    expect(lowercaseSide("SELL")).toBe("sell");
  });
});
