"use client";

import { useMemo } from "react";
import type { RulesOverview } from "@/lib/api/generated";
import { useApi, type ApiRead } from "@/lib/api/use-api";
import { useCockpit } from "@/lib/realtime/provider";
import { profileOf, type AccountProfile } from "./profile";

/** What changes the answer: a rule written or withdrawn, and everything the anti-tilt guard reads (a position, a trade, a lock). */
const RULES_EVENTS = [
  "account.rules_changed",
  "position.opened",
  "position.closed",
  "risk.lockout_enabled",
  "risk.lockout_cleared",
] as const;

/** The guard reads a clock too (a trading day starts, a deferred change takes effect): no event announces it. */
const RULES_POLL_MS = 30_000;

/**
 * The rules ledger of one account: the rules in force today, the change waiting for the next trading day, the history — and
 * what a change saved right now would do. All of it is the core's answer; nothing is resolved in the page.
 */
export function useRules(accountId: string | null): ApiRead<RulesOverview> {
  return useApi("accounts_rules", accountId ? { path: { account_id: accountId } } : null, {
    refreshOn: RULES_EVENTS,
    pollMs: RULES_POLL_MS,
  });
}

export interface ActiveProfile {
  /** Null while the rules are being read, or when no account is active. */
  profile: AccountProfile | null;
  error: Error | null;
}

/** The profile of the active account: its registry entry with the rules that govern it today. */
export function useActiveProfile(): ActiveProfile {
  const { registered } = useCockpit();
  const { data, error } = useRules(registered?.id ?? null);
  const profile = useMemo(
    () => (registered === null || data === null ? null : profileOf(registered, data.resolution.rules)),
    [registered, data],
  );
  return { profile, error };
}
