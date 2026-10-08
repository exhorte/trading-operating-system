"use client";

import { useEffect, useRef, useState } from "react";
import { TradeChart, type TradeChartProps } from "./trade-chart";

/** Narrowest chart that stays readable; a narrower container scrolls instead of squashing the candles. */
const MIN_WIDTH = 280;

/**
 * The capture chart sized to the room it has. `TradeChart` draws an SVG of a
 * fixed pixel width (its scales are computed from it), which overflowed any
 * container narrower than 720 px — a phone, or a desktop window with the
 * sidebar open. This frame measures its container (ResizeObserver) and hands
 * the width down; nothing about the drawing itself changes.
 */
export function TradeChartFrame(props: Omit<TradeChartProps, "width">) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const element = ref.current;
    if (!element) {
      return;
    }
    // A zero measure means « hidden for a moment » (a collapsed tab, a viewport being
    // resized), not « no room »: keep the last real width rather than unmounting the chart.
    const measure = (value: number) => {
      const next = Math.floor(value);
      if (next > 0) {
        setWidth(next);
      }
    };
    measure(element.getBoundingClientRect().width);
    const observer = new ResizeObserver(([entry]) => measure(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={ref} className="w-full overflow-x-auto rounded-lg border">
      {width > 0 && <TradeChart {...props} width={Math.max(MIN_WIDTH, width - 2)} />}
    </div>
  );
}
