"use client";

import { useState } from "react";
import { OctagonX } from "lucide-react";
import { useAcknowledgeLockout, useCockpit } from "@/lib/realtime/provider";
import { KILL_SWITCH_REASON } from "@/lib/api/generated";
import { Button } from "@/components/ui/button";

/**
 * T02a/T02c — persistent, full-width, and requires an explicit acknowledgment
 * before it goes away: renders for ANY untimed lockout (until === null), not
 * just the kill switch — daily loss and max trades do not auto-clear at the
 * next day anchor after two real incidents went unacknowledged overnight
 * (state.md, 2026-09-14/15). The kill switch keeps its own copy: the kill switch
 * itself never sends a close (closing is the separate « FERMER TOUTES LES
 * POSITIONS » button, ADR 0034, and a SIMULATED reply that closes nothing real
 * would be actively misleading), so its ack stays a manual-closure
 * certification, not just an acknowledgment.
 *
 * The lock is the one the core reports in the risk status; the reason the kill
 * switch is recorded under comes from the core too (generated.ts), not from a
 * copy kept here. A refused acknowledgement is shown, not swallowed.
 *
 * The text stays in the foreground colour (red on a red tint falls under 4.5:1
 * in light mode); only the lead-in and the icon carry the alarm colour.
 */
export function LockoutAckBanner() {
  const { activeLockout } = useCockpit();
  const acknowledgeLockout = useAcknowledgeLockout();
  const [state, setState] = useState<{ busy: boolean; error: string | null }>({ busy: false, error: null });

  if (!activeLockout || activeLockout.until !== null) {
    return null;
  }

  const isKillSwitch = activeLockout.reason === KILL_SWITCH_REASON;
  const lockoutId = activeLockout.lockoutId;

  async function acknowledge() {
    setState({ busy: true, error: null });
    try {
      await acknowledgeLockout(lockoutId);
      setState({ busy: false, error: null });
    } catch (error) {
      setState({ busy: false, error: error instanceof Error ? error.message : "Acquittement impossible." });
    }
  }

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
            {state.error && <span className="mt-1 block text-destructive">{state.error}</span>}
          </span>
        </p>
        <Button variant="destructive" size="sm" disabled={state.busy} onClick={() => void acknowledge()}>
          {isKillSwitch ? "J’ai fermé mes positions" : "J’en ai pris connaissance"}
        </Button>
      </div>
    </div>
  );
}
