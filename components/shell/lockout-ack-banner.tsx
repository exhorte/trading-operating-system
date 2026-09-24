"use client";

import { useAcknowledgeLockout, useCockpit } from "@/lib/realtime/provider";
import { KILL_SWITCH_REASON } from "@/lib/risk";

/**
 * T02a/T02c — persistent, full-width, and requires an explicit acknowledgment
 * before it goes away: renders for ANY untimed lockout (until === null), not
 * just the kill switch any more — daily loss and max trades stopped
 * auto-clearing at the next day anchor (clearedByForAck, shouldAutoClearForNewDay
 * removed) after two real incidents went unacknowledged overnight (state.md,
 * 2026-09-14/15). The kill switch keeps its own copy: no close_all command is
 * ever sent (the observer/wire has none, and a SIMULATED reply that closes
 * nothing real would be actively misleading), so its ack is a manual-closure
 * certification, not just an acknowledgment.
 */
export function LockoutAckBanner() {
  const { activeLockout } = useCockpit();
  const acknowledgeLockout = useAcknowledgeLockout();

  if (!activeLockout || activeLockout.until !== null) {
    return null;
  }

  const isKillSwitch = activeLockout.reason === KILL_SWITCH_REASON;

  return (
    <div className="flex shrink-0 items-center justify-between gap-4 border-b border-loss/30 bg-loss/10 px-4 py-3 text-sm text-loss md:px-6">
      <span>
        {isKillSwitch ? (
          <>
            <strong>Kill switch activé.</strong> Ferme tes positions dans MT5 maintenant — aucune
            commande de fermeture n&rsquo;est envoyée depuis ce dépôt, c&rsquo;est à toi de le faire.
          </>
        ) : (
          <>
            <strong>Lockout actif : {activeLockout.reason}.</strong> Il ne se lève plus tout seul au
            lendemain — confirme en avoir pris connaissance pour le lever.
          </>
        )}
      </span>
      <button
        type="button"
        onClick={() => acknowledgeLockout(activeLockout.lockoutId)}
        className="shrink-0 rounded-lg bg-loss/15 px-3.5 py-1.5 text-xs font-medium text-loss ring-1 ring-loss/40 transition-colors hover:bg-loss/25"
      >
        {isKillSwitch ? "J’ai fermé mes positions" : "J’en ai pris connaissance"}
      </button>
    </div>
  );
}
