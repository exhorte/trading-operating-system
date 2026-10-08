"use client";

import { OctagonX } from "lucide-react";
import { cn } from "cn";
import { useCockpit, useTriggerKillSwitch } from "@/lib/realtime/provider";

/**
 * T02a — the manual kill switch, one click from every screen: the bottom of
 * the sidebar (and of its mobile drawer), by the trader's choice.
 *
 * Locks the account for real (persisted ledger). Never touches the broker:
 * no close_all command exists, so closing positions stays a manual MT5
 * action (LockoutAckBanner says so).
 */
export function KillSwitchButton() {
  const { activeLockout } = useCockpit();
  const triggerKillSwitch = useTriggerKillSwitch();
  const locked = activeLockout !== null;

  return (
    <button
      type="button"
      onClick={triggerKillSwitch}
      disabled={locked}
      title={
        locked
          ? "Déjà verrouillé"
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
  );
}
