/**
 * Canonical <-> broker symbol registry (EA-04). The domain only ever speaks
 * EURUSD/GBPUSD/XAUUSD (SymbolCode); this module is the one place that knows
 * a given terminal calls them EURUSDm/GBPUSDm/XAUUSDm. No broker-specific
 * name may leak into lib/domain or lib/setup.
 *
 * Source data: context/domain/symbols-broker.md — measured 2026-09-12
 * (`list_symbols.py`, demo Exness 477029930, server Exness-MT5Trial9).
 * `contractSize` is the standard industry convention for each instrument
 * (100,000 base-currency units for FX majors, 100 oz for XAUUSD) — it was
 * not part of that measurement, unlike every other field below.
 *
 * XAUUSD note: the broker exposes both `XAUUSDm` and `XAUUSD247m`
 * (continuous/weekend quoting). `XAUUSDm` is the canonical entry here,
 * matching every other XAUUSD reference already in this repo (mock data,
 * `lib/risk/sizing-panel.ts`). `XAUUSD247m` is not registered — XAUUSD is
 * out of scope for S01 v1 (fiche S01, "Périmètre"), so nothing depends on
 * this choice yet.
 */

import type { SymbolCode } from "@/lib/domain/primitives";
import type { SymbolMetadata } from "@/lib/domain/market";

export interface BrokerSymbolEntry {
  canonical: SymbolCode;
  brokerName: string;
  metadata: SymbolMetadata;
}

const REGISTRY: Record<string, BrokerSymbolEntry> = {
  EURUSD: {
    canonical: "EURUSD",
    brokerName: "EURUSDm",
    metadata: {
      symbol: "EURUSD",
      description: "Euro vs US Dollar",
      baseCurrency: "EUR",
      quoteCurrency: "USD",
      tickSize: 0.00001,
      tickValue: 1.0,
      contractSize: 100_000,
      minVolume: 0.01,
      maxVolume: 200.0,
      volumeStep: 0.01,
      digits: 5,
    },
  },
  GBPUSD: {
    canonical: "GBPUSD",
    brokerName: "GBPUSDm",
    metadata: {
      symbol: "GBPUSD",
      description: "British Pound vs US Dollar",
      baseCurrency: "GBP",
      quoteCurrency: "USD",
      tickSize: 0.00001,
      tickValue: 1.0,
      contractSize: 100_000,
      minVolume: 0.01,
      maxVolume: 200.0,
      volumeStep: 0.01,
      digits: 5,
    },
  },
  XAUUSD: {
    canonical: "XAUUSD",
    brokerName: "XAUUSDm",
    metadata: {
      symbol: "XAUUSD",
      description: "Gold vs US Dollar",
      baseCurrency: "XAU",
      quoteCurrency: "USD",
      tickSize: 0.001,
      tickValue: 0.1,
      contractSize: 100,
      minVolume: 0.01,
      maxVolume: 200.0,
      volumeStep: 0.01,
      digits: 3,
    },
  },
};

const BY_BROKER_NAME: Record<string, SymbolCode> = Object.fromEntries(
  Object.values(REGISTRY).map((entry) => [entry.brokerName, entry.canonical]),
);

/** The broker-side name this terminal uses for a canonical symbol, or null
 *  if the symbol is not registered. */
export function toBrokerSymbol(canonical: SymbolCode): string | null {
  return REGISTRY[canonical]?.brokerName ?? null;
}

/** The canonical symbol for a broker-side name, or null if unknown. */
export function toCanonicalSymbol(brokerName: string): SymbolCode | null {
  return BY_BROKER_NAME[brokerName] ?? null;
}

/** Static broker metadata (tick size/value, volume bounds) for a canonical
 *  symbol, or null if unregistered. */
export function symbolMetadata(canonical: SymbolCode): SymbolMetadata | null {
  return REGISTRY[canonical]?.metadata ?? null;
}
