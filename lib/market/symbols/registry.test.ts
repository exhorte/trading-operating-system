import { describe, expect, it } from "vitest";
import { symbolMetadata, toBrokerSymbol, toCanonicalSymbol } from "./registry";

describe("toBrokerSymbol / toCanonicalSymbol", () => {
  it("maps the three registered symbols both ways", () => {
    expect(toBrokerSymbol("EURUSD")).toBe("EURUSDm");
    expect(toBrokerSymbol("GBPUSD")).toBe("GBPUSDm");
    expect(toBrokerSymbol("XAUUSD")).toBe("XAUUSDm");

    expect(toCanonicalSymbol("EURUSDm")).toBe("EURUSD");
    expect(toCanonicalSymbol("GBPUSDm")).toBe("GBPUSD");
    expect(toCanonicalSymbol("XAUUSDm")).toBe("XAUUSD");
  });

  it("returns null for an unregistered symbol in either direction", () => {
    expect(toBrokerSymbol("USDJPY")).toBeNull();
    expect(toCanonicalSymbol("USDJPYm")).toBeNull();
  });

  it("does not register the alternate XAUUSD247m broker name", () => {
    expect(toCanonicalSymbol("XAUUSD247m")).toBeNull();
  });
});

describe("symbolMetadata", () => {
  it("returns the measured tick value/size for EURUSD", () => {
    expect(symbolMetadata("EURUSD")).toMatchObject({
      symbol: "EURUSD",
      tickSize: 0.00001,
      tickValue: 1.0,
      digits: 5,
    });
  });

  it("returns null for an unregistered symbol", () => {
    expect(symbolMetadata("USDJPY")).toBeNull();
  });
});
