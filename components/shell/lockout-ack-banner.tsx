"use client";

import { OctagonX } from "lucide-react";
import { useAcknowledgeLockout, useCockpit } from "@/lib/realtime/provider";
import { KILL_SWITCH_REASON } from "@/lib/risk";
import { Button } from "@/components/ui/button";

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
 *
 * The text stays in the foreground colour (red on a red tint falls under 4.5:1
 * in light mode); only the lead-in and the icon carry the alarm colour.
 */
export function LockoutAckBanner() {
  const { activeLockout } = useCockpit();
  const acknowledgeLockout = useAcknowledgeLockout();

  if (!activeLockout || activeLockout.until !== null) {
    return null;
  }

  const isKillSwitch = activeLockout.reason === KILL_SWITCH_REASON;

  return (
    <div role="alert" className="border-b border-destructive/30 bg-destructive/10 px-4 sm:px-6 lg:px-10">
      <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 py-3 text-sm">
        <p className="flex min-w-0 items-start gap-2">
          <OctagonX className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden="true" />
          <span>
            {isKillSwitch ? (
              <>
                <strong className="text-destructive">Kill switch activé.</strong> Ferme tes positions dans MT5
                maintenant — aucune commande de fermeture n&rsquo;est envoyée depuis ce dépôt, c&rsquo;est à toi
                de le faire.
              </>
            ) : (
              <>
                <strong className="text-destructive">Lockout actif : {activeLockout.reason}.</strong> Il ne se
                lève plus tout seul au lendemain — confirme en avoir pris connaissance pour le lever.
              </>
            )}
          </span>
        </p>
        <Button variant="destructive" size="sm" onClick={() => acknowledgeLockout(activeLockout.lockoutId)}>
          {isKillSwitch ? "J’ai fermé mes positions" : "J’en ai pris connaissance"}
        </Button>
      </div>
    </div>
  );
}
