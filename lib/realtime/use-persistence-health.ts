"use client";

import { useEffect, useState } from "react";
import { backendHttpBase } from "./backend-url";

const POLL_INTERVAL_MS = 15_000;

export interface PersistenceHealth {
  status: string;
  db: string;
  persisted: number;
  dropped: number;
  queued: number;
  dbError: string | null;
}

export type PersistenceState =
  | { kind: "not_applicable" }
  | { kind: "unknown" }
  | { kind: "ok"; health: PersistenceHealth }
  | { kind: "issue"; health: PersistenceHealth };

/**
 * Polls the backend's /health for the persistence-writer counters (ADR 0003:
 * HTTP is the sanctioned surface for health/admin, not for trading flow).
 *
 * Why this exists: CockpitHub.PublishEvent broadcasts to every dashboard
 * BEFORE the write is even enqueued — a full queue or a down database drops
 * the write with zero effect on the broadcast. A published fact can
 * therefore echo back to the sender — proving the broadcast happened — while
 * never reaching the database. Only /health's `dropped` counter can catch
 * that case.
 *
 * Was the top bar's PersistenceHealthBadge until the 2026-09-24 redesign;
 * the account menu (always mounted, on every screen) now polls it and turns
 * its status dot red on an issue.
 */
export function usePersistenceHealth(): PersistenceState {
  const backendMode = process.env.NEXT_PUBLIC_REALTIME_SOURCE === "backend";
  const [state, setState] = useState<PersistenceState>(
    backendMode ? { kind: "unknown" } : { kind: "not_applicable" },
  );

  useEffect(() => {
    if (!backendMode) {
      return;
    }
    const url = `${backendHttpBase()}/health`;
    let cancelled = false;

    async function poll() {
      try {
        const res = await fetch(url, { cache: "no-store" });
        if (!res.ok) {
          throw new Error(String(res.status));
        }
        const health = (await res.json()) as PersistenceHealth;
        if (!cancelled) {
          setState({ kind: health.dropped > 0 || health.db !== "ok" ? "issue" : "ok", health });
        }
      } catch {
        if (!cancelled) {
          setState({ kind: "unknown" });
        }
      }
    }

    void poll();
    const timer = setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [backendMode]);

  return state;
}
