"use client";

import { useApi } from "@/lib/api/use-api";
import type { SystemHealthView } from "@/lib/api/generated";

const POLL_INTERVAL_MS = 15_000;

export type PersistenceState =
  | { kind: "unknown" }
  | { kind: "ok"; health: SystemHealthView }
  | { kind: "issue"; health: SystemHealthView; label: string };

/**
 * What the core says about its own memory: is the database up, and has an audit event ever been lost?
 *
 * Why this exists: a fact is broadcast to the cockpit before it is certain to be on disk, so a published fact can echo back —
 * proving it happened — while never reaching the database. Only the core's counters can catch that case, and the account menu
 * (always mounted, on every screen) turns its status dot red on one. `GET /api/system/health` is the one endpoint open without
 * the token: a launcher or a monitor reads the same figures.
 */
export function usePersistenceHealth(): PersistenceState {
  const { data } = useApi("system_health", {}, { pollMs: POLL_INTERVAL_MS, refreshOn: ["system.health_changed"] });
  return persistenceOf(data);
}

export function persistenceOf(health: SystemHealthView | null): PersistenceState {
  if (health === null) {
    return { kind: "unknown" };
  }
  if (!health.database.up) {
    return { kind: "issue", health, label: "base injoignable" };
  }
  if (health.audit.lost > 0) {
    return { kind: "issue", health, label: `${health.audit.lost} événement(s) d'audit perdu(s)` };
  }
  return { kind: "ok", health };
}
