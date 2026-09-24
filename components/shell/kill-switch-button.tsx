"use client";

import { OctagonX } from "lucide-react";
import { useCockpit, useTriggerKillSwitch } from "@/lib/realtime/provider";
import { SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar";

/**
 * T02a — the manual kill switch, one click from every screen. It left the
 * top bar in the 2026-09-24 redesign (only the account stays up there, as on
 * the reference mock-up) for the bottom of the sidebar, by the trader's
 * choice: still global, still one click.
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
    <SidebarMenuItem>
      <SidebarMenuButton
        onClick={triggerKillSwitch}
        disabled={locked}
        tooltip={locked ? "Déjà verrouillé" : "Arrêt d'urgence — verrouille le compte"}
        title={
          locked
            ? "Déjà verrouillé"
            : "Verrouille le compte immédiatement — les positions restent à fermer dans MT5"
        }
        className="gap-3 text-loss ring-1 ring-loss/25 hover:bg-loss/10 hover:text-loss disabled:opacity-40 [&>svg]:text-loss"
      >
        <OctagonX strokeWidth={1.75} />
        <span>{locked ? "Compte verrouillé" : "Arrêt d'urgence"}</span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}
