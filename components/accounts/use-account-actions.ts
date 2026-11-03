"use client";

import { useCallback, useState } from "react";
import { call, isApiError } from "@/lib/api/client";

/** The refusal of the core, in a shape a card can show: its sentence, and the structured reasons when it gave some. */
export interface ActionFailure {
  message: string;
  reasons: string[];
}

export function failureOf(error: unknown): ActionFailure {
  if (isApiError(error)) {
    const reasons = Array.isArray(error.details.reasons)
      ? error.details.reasons.filter((r): r is string => typeof r === "string")
      : [];
    return { message: error.message, reasons };
  }
  return { message: error instanceof Error ? error.message : "Action impossible.", reasons: [] };
}

export type ActionState = { status: "idle" } | { status: "busy"; what: string } | { status: "failed"; failure: ActionFailure };

/**
 * The gestures a card offers on one registered account. Each is a request to the core, which decides — attaching needs the
 * terminal to be logged into that very account, and detaching is refused while it could hide risk (an open
 * position, a pending order, a command in doubt); only one account is connected at a time (ADR 0021). The refusal comes back with its reasons and is shown as is; the new state
 * arrives through the stream (`account.*` events), not from this module.
 *
 * No password is asked here, and none is stored by the Trading OS: the terminal is logged in by the trader (ADR 0013).
 */
export function useAccountActions(accountId: string) {
  const [state, setState] = useState<ActionState>({ status: "idle" });

  const run = useCallback(async (what: string, work: () => Promise<unknown>) => {
    setState({ status: "busy", what });
    try {
      await work();
      setState({ status: "idle" });
    } catch (error) {
      setState({ status: "failed", failure: failureOf(error) });
    }
  }, []);

  return {
    state,
    connect: () => run("Rattachement…", () => call("accounts_connect", { path: { account_id: accountId } })),
    disconnect: () =>
      run("Détachement…", () => call("accounts_disconnect", { path: { account_id: accountId } })),
    setTrading: (enabled: boolean) =>
      run(enabled ? "Activation du trading…" : "Désactivation du trading…", () =>
        call("accounts_set_trading", { path: { account_id: accountId }, body: { enabled } }),
      ),
    archive: () => run("Archivage…", () => call("accounts_archive", { path: { account_id: accountId } })),
  };
}
