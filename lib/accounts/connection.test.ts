import { describe, expect, it } from "vitest";
import { AGENT_MAGIC_SUGGESTION, agentAllowedSymbols, observerCommand, terminalSymbol } from "./connection";

describe("connection procedure", () => {
  it("names instruments the way each firm's terminal does", () => {
    expect(terminalSymbol("exness", "XAUUSD")).toBe("XAUUSDm");
    expect(terminalSymbol("ftmo", "XAUUSD")).toBe("XAUUSD");
  });

  // mt5_observer.py defaults to XAUUSDm: run as-is against an FTMO terminal
  // it stops on « symbol not found ». The command must carry the right name.
  it("starts the observer on the symbol the terminal lists", () => {
    expect(observerCommand("ftmo")).toBe("python tools/mt5-observer/mt5_observer.py --symbol XAUUSD");
    expect(observerCommand("exness")).toBe("python tools/mt5-observer/mt5_observer.py --symbol XAUUSDm");
  });

  it("gives the EA-05 agent its whitelist in the terminal's own names", () => {
    expect(agentAllowedSymbols("exness")).toBe("EURUSDm,GBPUSDm");
    expect(agentAllowedSymbols("ftmo")).toBe("EURUSD,GBPUSD");
  });

  // ADR 0010: one magic number per account, never shared.
  it("never suggests the same magic number for two accounts", () => {
    expect(AGENT_MAGIC_SUGGESTION.ftmo).not.toBe(AGENT_MAGIC_SUGGESTION.exness);
    expect(AGENT_MAGIC_SUGGESTION.ftmo).toBeGreaterThan(0);
    expect(AGENT_MAGIC_SUGGESTION.exness).toBeGreaterThan(0);
  });
});
