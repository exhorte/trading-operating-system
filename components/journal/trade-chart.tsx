import type { Candle } from "@/lib/domain/market";
import type { MarketContextState } from "@/lib/domain/analysis";
import { computePriceScale, computeTimeScale } from "@/lib/journal/chart-scale";

export interface TradeChartMarker {
  price: number;
  label: string;
  tone: "entry" | "exit" | "stop" | "target";
}

export interface TradeChartProps {
  candles: Candle[];
  /** Null while loading, or when the window had too few candles to analyze —
   *  the chart still renders candles + markers without overlay levels. */
  context: MarketContextState | null;
  markers: TradeChartMarker[];
  width?: number;
  height?: number;
}

const MARKER_COLOR: Record<TradeChartMarker["tone"], string> = {
  entry: "var(--info)",
  exit: "var(--accent)",
  stop: "var(--loss)",
  target: "var(--profit)",
};

/**
 * T05 — the rendered capture: candles from lib/domain, overlays from
 * analyzeMarketContext (the canonical TypeScript analysis engine, ADR 0004 —
 * never re-implemented here), markers for entry/stop/take-profit/exit.
 * Rendered on demand from the immutable facts in `trade_captures`, not
 * pre-baked into an image (see T05-captures-auto.md for why).
 */
export function TradeChart({ candles, context, markers, width = 720, height = 320 }: TradeChartProps) {
  if (candles.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-xs text-muted"
        style={{ width, height }}
      >
        No candles in the captured window.
      </div>
    );
  }

  const priceScale = computePriceScale(
    candles,
    height,
    markers.map((m) => m.price),
  );
  const timeScale = computeTimeScale(candles.length, width);
  const candleWidth = Math.max(2, timeScale.slotWidth * 0.6);

  return (
    <svg width={width} height={height} role="img" aria-label="Trade capture chart">
      <rect x={0} y={0} width={width} height={height} fill="var(--surface)" />

      {context?.activeFairValueGaps.map((fvg) => (
        <rect
          key={fvg.fvgId}
          x={0}
          y={priceScale.toY(fvg.high)}
          width={width}
          height={Math.max(1, priceScale.toY(fvg.low) - priceScale.toY(fvg.high))}
          fill={fvg.direction === "bullish" ? "var(--profit)" : "var(--loss)"}
          fillOpacity={0.08}
        />
      ))}

      {context?.activeOrderBlocks.map((ob) => (
        <rect
          key={ob.orderBlockId}
          x={0}
          y={priceScale.toY(ob.high)}
          width={width}
          height={Math.max(1, priceScale.toY(ob.low) - priceScale.toY(ob.high))}
          fill={ob.direction === "bullish" ? "var(--profit)" : "var(--loss)"}
          fillOpacity={0.16}
        />
      ))}

      {context?.activeLiquidityLevels.map((level) => (
        <line
          key={level.levelId}
          x1={0}
          x2={width}
          y1={priceScale.toY(level.price)}
          y2={priceScale.toY(level.price)}
          stroke="var(--warning)"
          strokeDasharray="4 3"
          strokeWidth={1}
        />
      ))}

      {candles.map((candle, i) => {
        const x = timeScale.toX(i);
        const bullish = candle.close >= candle.open;
        const color = bullish ? "var(--profit)" : "var(--loss)";
        const bodyTop = priceScale.toY(Math.max(candle.open, candle.close));
        const bodyBottom = priceScale.toY(Math.min(candle.open, candle.close));
        return (
          <g key={candle.openTime}>
            <line
              x1={x}
              x2={x}
              y1={priceScale.toY(candle.high)}
              y2={priceScale.toY(candle.low)}
              stroke={color}
              strokeWidth={1}
            />
            <rect
              x={x - candleWidth / 2}
              y={bodyTop}
              width={candleWidth}
              height={Math.max(1, bodyBottom - bodyTop)}
              fill={color}
            />
          </g>
        );
      })}

      {markers.map((marker) => (
        <g key={`${marker.tone}-${marker.price}`}>
          <line
            x1={0}
            x2={width}
            y1={priceScale.toY(marker.price)}
            y2={priceScale.toY(marker.price)}
            stroke={MARKER_COLOR[marker.tone]}
            strokeWidth={1.5}
            strokeDasharray={marker.tone === "entry" || marker.tone === "exit" ? undefined : "2 2"}
          />
          <text x={4} y={priceScale.toY(marker.price) - 3} fill={MARKER_COLOR[marker.tone]} fontSize={10}>
            {marker.label} {marker.price}
          </text>
        </g>
      ))}
    </svg>
  );
}
