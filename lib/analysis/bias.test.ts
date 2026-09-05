import { describe, expect, it } from "vitest";
import { computeBias, priceLocationOf } from "./bias";
import type { Swing } from "./types";

const swings: Swing[] = [
  { kind: "high", price: 12, index: 1, time: "t" },
  { kind: "low", price: 8, index: 3, time: "t" },
];

describe("computeBias", () => {
  it("follows structural bias in the MVP", () => {
    expect(computeBias("bullish")).toBe("bullish");
    expect(computeBias("neutral")).toBe("neutral");
  });
});

describe("priceLocationOf", () => {
  it("classifies premium, discount and equilibrium within the swing range", () => {
    expect(priceLocationOf(11.5, swings)).toBe("premium");
    expect(priceLocationOf(8.5, swings)).toBe("discount");
    expect(priceLocationOf(10, swings)).toBe("equilibrium");
  });

  it("returns equilibrium when a side of the range is missing", () => {
    expect(priceLocationOf(10, [{ kind: "high", price: 12, index: 1, time: "t" }])).toBe(
      "equilibrium",
    );
  });
});
