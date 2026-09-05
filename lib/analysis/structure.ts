/**
 * Market-structure detection: BOS (break of structure) and CHOCH (change of
 * character).
 *
 * A close beyond the most recent known swing is a BOS when it extends the
 * prevailing bias, or a CHOCH when it breaks against it (the first sign of a
 * reversal). Swings are only "known" `lookback` candles after they form, so a
 * candle can never break a pivot the market had not yet confirmed
 * (no look-ahead).
 */

import type { Candle } from "@/lib/domain/market";
import type { Bias } from "@/lib/domain/primitives";
import type { StructureShift } from "@/lib/domain/analysis";
import type { Swing } from "./types";

export function detectStructureShifts(
  candles: Candle[],
  swings: Swing[],
  lookback: number,
): StructureShift[] {
  const shifts: StructureShift[] = [];
  if (candles.length === 0) {
    return shifts;
  }

  const { symbol, timeframe } = candles[0];
  const sorted = [...swings].sort((a, b) => a.index - b.index);

  let cursor = 0;
  let lastHigh: Swing | null = null;
  let lastLow: Swing | null = null;
  let brokenHighIndex = -1;
  let brokenLowIndex = -1;
  let bias: Bias = "neutral";

  for (let t = 0; t < candles.length; t += 1) {
    // Promote every swing confirmed by time t into the "known" reference set.
    while (cursor < sorted.length && sorted[cursor].index + lookback <= t) {
      const swing = sorted[cursor];
      if (swing.kind === "high") {
        lastHigh = swing;
      } else {
        lastLow = swing;
      }
      cursor += 1;
    }

    const close = candles[t].close;

    if (lastHigh && lastHigh.index !== brokenHighIndex && close > lastHigh.price) {
      const kind = bias === "bearish" ? "change_of_character" : "break_of_structure";
      shifts.push({
        shiftId: `shift-${t}`,
        symbol,
        timeframe,
        kind,
        direction: "bullish",
        brokenLevel: lastHigh.price,
        occurredAt: candles[t].openTime,
      });
      brokenHighIndex = lastHigh.index;
      bias = "bullish";
    } else if (lastLow && lastLow.index !== brokenLowIndex && close < lastLow.price) {
      const kind = bias === "bullish" ? "change_of_character" : "break_of_structure";
      shifts.push({
        shiftId: `shift-${t}`,
        symbol,
        timeframe,
        kind,
        direction: "bearish",
        brokenLevel: lastLow.price,
        occurredAt: candles[t].openTime,
      });
      brokenLowIndex = lastLow.index;
      bias = "bearish";
    }
  }

  return shifts;
}

/** Structural bias implied by the most recent shift, neutral if none. */
export function structuralBias(shifts: StructureShift[]): Bias {
  const last = shifts.at(-1);
  return last ? last.direction : "neutral";
}
