/**
 * Market data models: symbols, ticks, candles, spread, sessions.
 * Producers: MT5 agent (live) or mock generators; consumers: analysis
 * engines, risk gates, and the dashboard.
 */

import type { SymbolCode, TradingSession, Timeframe, UtcTimestamp } from "./primitives";

/** Static/broker metadata needed to size and price orders on a symbol. */
export interface SymbolMetadata {
  symbol: SymbolCode;
  description: string;
  baseCurrency: string;
  quoteCurrency: string;
  /** Smallest price increment, e.g. 0.01 for XAUUSD. */
  tickSize: number;
  /** Account-currency value of one tickSize move for 1.0 lot. */
  tickValue: number;
  /** Units per 1.0 lot, e.g. 100 oz for XAUUSD. */
  contractSize: number;
  minVolume: number;
  maxVolume: number;
  volumeStep: number;
  /** Price decimal places the broker quotes. */
  digits: number;
}

export interface Tick {
  symbol: SymbolCode;
  bid: number;
  ask: number;
  /** Last trade price when the venue provides it, else null. */
  last: number | null;
  timestamp: UtcTimestamp;
}

export interface Candle {
  symbol: SymbolCode;
  timeframe: Timeframe;
  /** Candle open time (bucket start), UTC. */
  openTime: UtcTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
  /** Tick volume as reported by the venue. */
  volume: number;
  /** False while the candle is still forming. */
  closed: boolean;
}

/** Point-in-time spread observation used by spread safety gates. */
export interface SpreadSample {
  symbol: SymbolCode;
  spreadPoints: number;
  timestamp: UtcTimestamp;
}

/** Configured trading window for a session (times are UTC "HH:mm"). */
export interface SessionWindow {
  session: TradingSession;
  startUtc: string;
  endUtc: string;
  /** Whether strategies may trade during this window. */
  tradingEnabled: boolean;
}
