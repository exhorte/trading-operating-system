"use client";

import { useMemo } from "react";
import { useCockpit } from "@/lib/realtime/provider";
import {
  resolveAccountSettings,
  type AccountSettingsLedger,
  type ResolvedAccountSettings,
} from "./settings";

export interface AccountSettingsView {
  /** Null until the first read of the ledger succeeds. */
  ledger: AccountSettingsLedger | null;
  /** Why the last read failed, or null. */
  error: string | null;
  /** Settings in effect today, per firm, with their source and any pending
   *  change — the code's defaults when the ledger is empty or unread. */
  resolved: ResolvedAccountSettings;
  /** Trading-day anchor the resolution used, or null when none is known. */
  anchor: string | null;
}

/**
 * T12 incrément 2 — the same resolution the risk engine applies
 * (signalr-client.ts::recomputeRisk), for the screens: what they show as "in
 * effect" is what the gates are using.
 */
export function useAccountSettings(): AccountSettingsView {
  const { accountSettings, accountSettingsError, dayAnchorStartsAtUtc } = useCockpit();
  const resolved = useMemo(
    () => resolveAccountSettings(accountSettings?.versions ?? [], dayAnchorStartsAtUtc),
    [accountSettings, dayAnchorStartsAtUtc],
  );
  return {
    ledger: accountSettings,
    error: accountSettingsError,
    resolved,
    anchor: dayAnchorStartsAtUtc,
  };
}
