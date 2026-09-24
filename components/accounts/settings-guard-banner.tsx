import {
  describeGuardReason,
  type AccountSettingsLedger,
} from "@/lib/accounts/settings";
import { formatDateTime } from "./form-controls";

/**
 * « Si j'enregistre maintenant, ça s'applique quand ? » — answered by the
 * backend (AccountSettingsGuard), displayed here, never computed here. The
 * answer can change by the time of saving (a trade, a lockout); the backend
 * decides again at that instant and the form reports what it decided.
 */
export function SettingsGuardBanner({
  ledger,
  error,
}: {
  ledger: AccountSettingsLedger | null;
  error: string | null;
}) {
  if (!ledger) {
    return error ? (
      <div className="rounded border border-loss/40 bg-loss/10 px-3 py-2 text-xs text-loss">
        Backend injoignable ({error}) : rien ne peut être enregistré, et le moteur de risque
        applique les valeurs par défaut du code.
      </div>
    ) : (
      <div className="rounded border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
        Lecture des paramètres…
      </div>
    );
  }

  const { guard } = ledger;
  return (
    <div
      className={`rounded border px-3 py-2 text-xs ${
        guard.deferred
          ? "border-warning/40 bg-warning/10 text-warning"
          : "border-profit/40 bg-profit/10 text-profit"
      }`}
    >
      <p className="font-medium">
        {guard.deferred
          ? "Un changement enregistré maintenant s'appliquera au prochain jour de trading."
          : "Un changement enregistré maintenant s'appliquera immédiatement : aucune séance n'est en cours."}
      </p>
      {guard.deferred && guard.reasons.length > 0 && (
        <ul className="mt-1 list-disc pl-4 text-foreground">
          {guard.reasons.map((reason, i) => (
            <li key={`${reason.code}-${reason.accountId ?? i}`}>{describeGuardReason(reason)}</li>
          ))}
        </ul>
      )}
      <p className="mt-1 text-xs text-muted-foreground">
        Une limite ne se desserre jamais en pleine séance : le backend en décide au moment
        d&apos;enregistrer (ADR 0007). Évalué le {formatDateTime(ledger.evaluatedAt)}
        {error ? ` — dernière relecture échouée (${error}), la dernière configuration lue reste appliquée` : ""}.
      </p>
    </div>
  );
}
