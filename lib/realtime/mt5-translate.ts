/**
 * Pure translation: lean MT5 edge messages (lib/contracts/mt5-wire) → dashboard
 * read models (lib/contracts/snapshots) and domain candles.
 *
 * Since Phase 08 this translation runs SERVER-SIDE in the .NET gateway
 * (backend/src/TradingOs.Gateway/Mt5WireTranslator.cs, ADR 0009); the former
 * browser LiveRealtimeClient was deleted after live validation. This module and
 * its tests are kept as the canonical TS reference the C# port mirrors 1:1 —
 * change both sides together.
 */

import type {
  Mt5AccountSnapshotMessage,
  Mt5CandleMessage,
  Mt5HelloMessage,
  Mt5PositionsSnapshotMessage,
  Mt5PositionSnapshot,
  Mt5Side,
} from "@/lib/contracts/mt5-wire";
import type { AccountSummary, AgentStatus, Position } from "@/lib/contracts/snapshots";
import type { Candle } from "@/lib/domain/market";
import type { Side, Timeframe } from "@/lib/domain/primitives";

export function lowercaseSide(side: Mt5Side): Side {
  return side === "BUY" ? "buy" : "sell";
}

function iso(epochMs: number): string {
  return new Date(epochMs).toISOString();
}

/**
 * Real fields (balance, equity, currency) come straight from MT5. dailyPnl is
 * the floating P&L (equity − balance) — a genuine number but an intraday
 * approximation of "daily". Drawdown and open-risk percentages stay 0 until a
 * risk engine + day baseline exist; they are never presented as validated risk.
 */
export function toAccountSummary(
  account: Mt5AccountSnapshotMessage,
  hello: Mt5HelloMessage | null,
): AccountSummary {
  return {
    accountId: account.accountId,
    label: hello ? `${hello.broker} • ${account.accountId}` : account.accountId,
    broker: hello?.broker ?? "MT5",
    currency: account.currency,
    balance: account.balance,
    equity: account.equity,
    dailyPnl: Math.round((account.equity - account.balance) * 100) / 100,
    dailyDrawdownPercent: 0,
    totalDrawdownPercent: 0,
    openRiskPercent: 0,
  };
}

function toPosition(
  p: Mt5PositionSnapshot,
  accountId: string,
  openedAtIso: string,
  lastPrice: number | null,
): Position {
  const side = lowercaseSide(p.side);
  const currentPrice = lastPrice ?? p.entryPrice;
  const direction = side === "buy" ? 1 : -1;
  const move = (currentPrice - p.entryPrice) * direction;
  const risk = Math.abs(p.entryPrice - p.stopLoss);
  return {
    positionId: p.brokerPositionId,
    accountId,
    symbol: p.symbol,
    side,
    volume: p.volume,
    entryPrice: p.entryPrice,
    currentPrice,
    stopLoss: p.stopLoss,
    takeProfit: p.takeProfit,
    unrealizedPnl: p.floatingPnl,
    rMultiple: risk > 0 ? Math.round((move / risk) * 100) / 100 : 0,
    strategyId: "live-observed",
    openedAt: openedAtIso,
  };
}

export function toPositions(
  msg: Mt5PositionsSnapshotMessage,
  lastPrice: number | null,
): Position[] {
  const openedAtIso = iso(msg.time);
  return msg.positions.map((p) => toPosition(p, msg.accountId, openedAtIso, lastPrice));
}

export function toCandle(msg: Mt5CandleMessage): Candle {
  return {
    symbol: msg.symbol,
    timeframe: msg.timeframe as Timeframe,
    openTime: iso(msg.openTime),
    open: msg.open,
    high: msg.high,
    low: msg.low,
    close: msg.close,
    volume: msg.volume,
    closed: msg.closed,
  };
}

export function toAgentStatus(hello: Mt5HelloMessage): AgentStatus {
  return {
    agentId: hello.agentId,
    accountId: hello.accountId,
    platform: "MT5",
    state: "connected",
    latencyMs: 0,
    lastHeartbeatAt: iso(hello.time),
    version: hello.agentVersion,
  };
}
