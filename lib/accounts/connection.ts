/**
 * How a firm's MT5 terminal gets attached to the cockpit (T12 incrément 2) —
 * the facts behind the connection procedure shown in Settings.
 *
 * "Connecting" an account never happens in this application: the trader
 * logs into the account in MT5, where the password stays (ADR 0003), then
 * starts the read-only observer against that terminal. What differs between
 * firms is only how their terminal names instruments — Exness suffixes `m`
 * (measured, lib/market/symbols/registry.ts), FTMO uses the canonical name
 * (MetriX export). The observer refuses to start on a symbol its terminal
 * does not list, which is exactly the failure a wrong default would cause:
 * `mt5_observer.py` defaults to `XAUUSDm`, so run as-is against an FTMO
 * terminal it stops with « symbol not found ».
 */

import type { SymbolCode } from "@/lib/domain/primitives";
import { toBrokerSymbol } from "@/lib/market/symbols/registry";
import type { Firm } from "./firm";

/** The instrument name in a firm's terminal. */
export function terminalSymbol(firm: Firm, canonical: SymbolCode): string {
  return firm === "exness" ? (toBrokerSymbol(canonical) ?? canonical) : canonical;
}

/** The command that attaches the read-only observer to the open terminal,
 *  run from `04_code`. The symbol is the one the cockpit's spread gate is
 *  calibrated for (XAUUSD points, lib/risk/policy.ts). */
export function observerCommand(firm: Firm): string {
  return `python tools/mt5-observer/mt5_observer.py --symbol ${terminalSymbol(firm, "XAUUSD")}`;
}

/** `InpAllowedSymbolsCsv` of the EA-05 agent for this firm's terminal — the
 *  pairs the trader works, in that terminal's names (the input's default is
 *  Exness's). XAUUSD and EURUSD since 2026-09-25 (user decision; GBPUSD set
 *  aside for later). */
export function agentAllowedSymbols(firm: Firm): string {
  return (["XAUUSD", "EURUSD"] as const).map((symbol) => terminalSymbol(firm, symbol)).join(",");
}

/**
 * A suggested `InpMagicNumber` per firm. ADR 0010 only requires that no two
 * accounts share one (it keys the agent's command store and tells its own
 * positions from external ones); fixed suggestions just make that the easy
 * path. Mirrored in scripts/start-live.ps1, which prints the same values.
 */
export const AGENT_MAGIC_SUGGESTION: Record<Firm, number> = { exness: 1001, ftmo: 2001 };

/** One command that brings the whole live environment up for whichever
 *  account MT5 has open — it detects the firm and the symbol itself. */
export const START_LIVE_COMMAND = "pwsh -File scripts\\start-live.ps1";
