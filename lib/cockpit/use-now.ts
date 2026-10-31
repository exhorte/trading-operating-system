"use client";

import { useEffect, useState } from "react";

/**
 * The current time, as render-safe state: it moves on a clock, not on every render, so a component that shows « in 12 min » can
 * be pure. Re-renders once per `periodMs`.
 */
export function useNow(periodMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const interval = setInterval(() => setNow(Date.now()), periodMs);
    return () => clearInterval(interval);
  }, [periodMs]);
  return now;
}
