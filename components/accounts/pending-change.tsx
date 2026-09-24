"use client";

import { useState } from "react";
import { useRefreshAccountSettings } from "@/lib/realtime/provider";
import { cancelSettingsChange } from "@/lib/accounts/settings-api";
import { describeVersion, isCancellable, type SettingsVersion } from "@/lib/accounts/settings";
import { formatDateTime, secondaryButtonClass } from "./form-controls";

/**
 * A change waiting for the next trading day. Withdrawing it is offered only
 * while no trading day has started since it was requested (the backend
 * refuses otherwise — it may have governed a session somewhere).
 */
export function PendingChange({
  version,
  allowCancel = true,
}: {
  version: SettingsVersion;
  allowCancel?: boolean;
}) {
  const refresh = useRefreshAccountSettings();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancellable = allowCancel && isCancellable(version, "en_attente");

  async function cancel() {
    setBusy(true);
    setError(null);
    try {
      await cancelSettingsChange(version.versionId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Annulation impossible.");
    } finally {
      setBusy(false);
      refresh();
    }
  }

  return (
    <div className="rounded border border-warning/40 bg-warning/5 px-2.5 py-2 text-xs leading-snug">
      <div className="flex items-start justify-between gap-2">
        <p className="text-foreground">
          <span className="font-medium text-warning">En attente du prochain jour de trading</span>
          {" — "}
          {describeVersion(version)}
          <span className="text-muted-foreground"> (demandé le {formatDateTime(version.requestedAt)})</span>
        </p>
        {cancellable && (
          <button type="button" onClick={cancel} disabled={busy} className={secondaryButtonClass}>
            {busy ? "…" : "Annuler"}
          </button>
        )}
      </div>
      {error && <p className="mt-1 text-loss">{error}</p>}
    </div>
  );
}
