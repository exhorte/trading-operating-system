/**
 * accountId -> AccountProfile lookup (EA-04). Pure function over an
 * explicit registry so it's testable without a hidden module singleton
 * (same pattern as lib/contracts/execution/idempotency.ts).
 *
 * `ACCOUNT_PROFILES` is the real registry `lib/risk/policy.ts` consults. It
 * is empty today — no FTMO or real account has been confirmed to exist yet
 * (open question in context/project/state.md) — on purpose: registering a
 * placeholder account here would be a guess, not a fact. Every current
 * caller of `defaultRiskPolicy` keeps working unchanged against its
 * hardcoded fallback until an account is actually added here.
 */

import type { AccountId } from "@/lib/domain/primitives";
import type { AccountProfile } from "./types";

export type AccountProfileRegistry = Readonly<Record<string, AccountProfile>>;

export function resolveAccountProfile(
  registry: AccountProfileRegistry,
  accountId: AccountId,
): AccountProfile | null {
  return registry[accountId] ?? null;
}

/** The registry lib/risk/policy.ts consults. Add an entry once a real FTMO
 *  or real-money account exists and its details are confirmed. */
export const ACCOUNT_PROFILES: AccountProfileRegistry = {};
