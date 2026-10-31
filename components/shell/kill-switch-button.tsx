"use client";

import { useState } from "react";
import { OctagonX } from "lucide-react";
import { cn } from "cn";
import { useCockpit, useTriggerKillSwitch } from "@/lib/realtime/provider";

/**
 * T02a — the manual kill switch, one click from every screen: the bottom of
 * the sidebar (and of its mobile drawer), by the trader's choice.
 *
 * Locks the account for real, in the core's ledger. Never touches the broker:
 * no close_all command exists, so closing positions stays a manual MT5
 * action (LockoutAckBanner says so). A refusal — the core down, no account
 * attached — is shown under the button, never swallowed: an emergency stop
 * that silently did nothing is the worst failure this button can have.
 */
export function KillSwitchButton() {
  const { activeLockout, activeAccountId } = useCockpit();
  const triggerKillSwitch = useTriggerKillSwitch();
  const [state, setState] = useState<{ busy: boolean; error: string | null }>({ busy: false, error: null });
  const locked = activeLockout !== null;
  const nothingToLock = activeAccountId === null;

  async function engage() {
    setState({ busy: true, error: null });
    try {
      await triggerKillSwitch();
      setState({ busy: false, error: null });
    } catch (error) {
      setState({ busy: false, error: error instanceof Error ? error.message : "Verrouillage impossible." });
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <button
        type="button"
        onClick={() => void engage()}
        disabled={locked || nothingToLock || state.busy}
        title={
          locked
            ? "Déjà verrouillé"
            : nothingToLock
              ? "Aucun compte actif : rien à verrouiller"
              : "Verrouille le compte immédiatement — les positions restent à fermer dans MT5"
        }
        className={cn(
          "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-destructive outline-none",
          "ring-1 ring-destructive/30 transition-colors hover:bg-destructive/10",
          "focus-visible:ring-[3px] focus-visible:ring-destructive/40 disabled:pointer-events-none disabled:opacity-50",
          "[&_svg]:size-4 [&_svg]:shrink-0",
        )}
      >
        <OctagonX aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate text-left">{locked ? "Compte verrouillé" : "Arrêt d'urgence"}</span>
      </button>
      {state.error && (
        <p role="alert" className="px-3 text-xs leading-snug text-destructive">
          {state.error}
        </p>
      )}
    </div>
  );
}
