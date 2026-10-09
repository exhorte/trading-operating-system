import type { RulesOverview } from "@/lib/api/generated";
import { describeGuardReason } from "@/lib/accounts/guard-text";
import { Callout } from "@/components/ui/callout";
import { formatDateTime } from "./form-controls";

/**
 * « Si j'enregistre maintenant, ça s'applique quand ? » — answered by the
 * core's anti-tilt guard, displayed here, never computed here. The answer can
 * change by the time of saving (a trade, a lockout); the core decides again at
 * that instant and the form reports what it decided.
 */
export function SettingsGuardBanner({
  overview,
  error,
}: {
  overview: RulesOverview | null;
  error: Error | null;
}) {
  if (!overview) {
    return error ? (
      <Callout title="Règles illisibles" variant="warning">
        {error.message} : rien ne peut être enregistré tant que le cœur ne répond pas.
      </Callout>
    ) : (
      <p className="rounded-xl border px-5 py-4 text-sm text-muted-foreground">Lecture des règles…</p>
    );
  }

  const { guard } = overview;
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
      Une limite ne se desserre jamais en pleine séance : le cœur en décide au moment d&apos;enregistrer (ADR 0007).
      Évalué le {formatDateTime(overview.evaluatedAt)}
      {error ? ` — dernière relecture échouée (${error.message}), la dernière configuration lue reste affichée` : ""}.
    </Callout>
  );
}
