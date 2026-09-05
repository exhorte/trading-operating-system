"use client";

import { useAcknowledgeLockout, useCockpit } from "@/lib/realtime/provider";
import { KILL_SWITCH_REASON } from "@/lib/risk";

/**
 * T02a — persistent, full-width, and requires an explicit acknowledgment
 * before it goes away. No close_all command is ever sent (the observer/wire
 * has none, and a SIMULATED reply that closes nothing real would be actively
 * misleading) — this banner, and the ack it demands, are the only real
 * effect of the kill switch besides the lock itself.
 */
export function KillSwitchBanner() {
  const { activeLockout } = useCockpit();
  const acknowledgeLockout = useAcknowledgeLockout();

  if (!activeLockout || activeLockout.reason !== KILL_SWITCH_REASON) {
    return null;
  }

  return (
    <div className="flex shrink-0 items-center justify-between gap-3 border-b border-loss/40 bg-loss/15 px-4 py-2 text-sm text-loss">
      <span>
        <strong>Kill switch activé.</strong> Ferme tes positions dans MT5 maintenant — aucune
        commande de fermeture n&rsquo;est envoyée depuis ce dépôt, c&rsquo;est à toi de le faire.
      </span>
      <button
        type="button"
        onClick={() => acknowledgeLockout(activeLockout.lockoutId)}
        className="shrink-0 rounded border border-loss/50 bg-surface px-3 py-1 text-xs font-medium text-loss hover:bg-loss/20"
      >
        J&rsquo;ai fermé mes positions
      </button>
    </div>
  );
}
