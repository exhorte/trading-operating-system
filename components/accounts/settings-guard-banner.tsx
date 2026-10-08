import {
  describeGuardReason,
  type AccountSettingsLedger,
} from "@/lib/accounts/settings";
import { Callout } from "@/components/ui/callout";
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
      <Callout title="Backend injoignable" variant="warning">
        {error} : rien ne peut être enregistré, et le moteur de risque applique les valeurs par défaut du code.
      </Callout>
    ) : (
      <p className="rounded-xl border px-5 py-4 text-sm text-muted-foreground">Lecture des paramètres…</p>
    );
  }

  const { guard } = ledger;
  return (
    <Callout
      variant={guard.deferred ? "warning" : "info"}
      title={
        guard.deferred
          ? "Un changement enregistré maintenant s'appliquera au prochain jour de trading."
          : "Un changement enregistré maintenant s'appliquera immédiatement : aucune séance n'est en cours."
      }
    >
      {guard.deferred && guard.reasons.length > 0 && (
        <ul className="mb-2 list-disc pl-4 text-foreground">
          {guard.reasons.map((reason, i) => (
            <li key={`${reason.code}-${reason.accountId ?? i}`}>{describeGuardReason(reason)}</li>
          ))}
        </ul>
      )}
      Une limite ne se desserre jamais en pleine séance : le backend en décide au moment d&apos;enregistrer (ADR
      0007). Évalué le {formatDateTime(ledger.evaluatedAt)}
      {error ? ` — dernière relecture échouée (${error}), la dernière configuration lue reste appliquée` : ""}.
    </Callout>
  );
}
