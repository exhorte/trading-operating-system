/**
 * Converts a CostModel's per-lot commission into price-distance units
 * comparable to spread and stop distance — lib/setup/gates.ts is explicit
 * that `spread` and `commission` "must already be in the same price units as
 * stopDistance". `tickValue` is the account-currency value of one `tickSize`
 * move for 1.0 lot, so `tickSize / tickValue` converts a currency amount
 * into price units for that symbol. Pure.
 */

import type { SymbolCode } from "@/lib/domain/primitives";
import type { SymbolMetadata } from "@/lib/domain/market";
import type { CostModel } from "./types";

export function commissionInPriceUnits(
  costModel: CostModel,
  metadata: SymbolMetadata,
): number {
  if (metadata.tickValue <= 0) {
    return 0;
  }
  return costModel.commissionPerLotRoundTrip * (metadata.tickSize / metadata.tickValue);
}

/** Documented expected spread for a symbol, or null if the model has none —
 *  never a substitute for the gate's live spread read. */
export function expectedSpread(costModel: CostModel, symbol: SymbolCode): number | null {
  return costModel.expectedSpreadBySymbol[symbol] ?? null;
}
