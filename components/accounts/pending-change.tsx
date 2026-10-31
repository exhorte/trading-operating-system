"use client";

import { useState } from "react";
import type { AccountRules, RuleVersionView } from "@/lib/api/generated";
import { call } from "@/lib/api/client";
import { describeChange } from "@/lib/accounts/rules-draft";
import { describeGuardReasons } from "@/lib/accounts/guard-text";
import { failureOf } from "./use-account-actions";
import { formatDateTime, secondaryButtonClass } from "./form-controls";

/**
 * A change waiting for the next trading day, with what it would change. Withdrawing it is offered only while no trading day has
 * started since it was requested (the core says so in `cancellable`, and refuses otherwise — it may have governed a session
 * somewhere).
 */
export function PendingChange({
  version,
  inForce,
  onChanged,
}: {
  version: RuleVersionView;
  /** The rules in force now — the changes are shown against them. */
  inForce: AccountRules;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changes = describeChange(inForce, version.rules);

  async function cancel() {
    setBusy(true);
    setError(null);
    try {
      await call("accounts_cancel_rules", {
        path: { account_id: version.accountId, version_id: version.versionId },
      });
    } catch (e) {
      setError(failureOf(e).message);
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  return (
    <div className="rounded-lg border border-warning/30 bg-warning/5 px-3 py-2.5 text-sm leading-snug">
      <div className="flex items-start justify-between gap-2">
        <p className="text-foreground">
          <span className="font-medium text-warning">En attente du prochain jour de trading</span>
          <span className="text-muted-foreground"> (demandé le {formatDateTime(version.requestedAt)})</span>
        </p>
        {version.cancellable && (
          <button type="button" onClick={() => void cancel()} disabled={busy} className={secondaryButtonClass}>
            {busy ? "…" : "Annuler"}
          </button>
        )}
      </div>
      {changes.length > 0 && (
        <ul className="mt-1.5 list-disc pl-4 text-foreground">
          {changes.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
      {version.deferralReasons.length > 0 && (
        <p className="mt-1.5 text-muted-foreground">Reporté parce que : {describeGuardReasons(version.deferralReasons)}</p>
      )}
      {error && <p className="mt-1 text-destructive">{error}</p>}
    </div>
  );
}
