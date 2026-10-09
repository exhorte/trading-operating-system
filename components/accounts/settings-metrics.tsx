import { Clock, History, Landmark, ShieldCheck, SlidersHorizontal } from "lucide-react";
import type { Account, RulesOverview } from "@/lib/api/generated";
import { formatCapital, PROVIDER_NAMES } from "@/lib/accounts/profile";
import { HighlightBar, MetricPanel, MetricPanelItem } from "@/components/ui/metric-panel";

const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });

/**
 * What is in force, and when a change would take effect, in the dark panel
 * (ADR 0017) — the « aperçu en direct » of a settings form. The headline is
 * the core's own answer to « si j'enregistre maintenant, ça s'applique
 * quand ? » (the anti-tilt guard): « Immédiat », or « Différé » to the next
 * trading day — displayed here, never computed here. Kept to one short word:
 * on a phone the headline shares its row with the label. Without a read
 * ledger nothing is guessed: dashes, and the reason.
 */
export function SettingsMetrics({
  account,
  overview,
  error,
}: {
  account: Account | null;
  overview: RulesOverview | null;
  error: Error | null;
}) {
  const rules = overview?.resolution.rules ?? null;
  const reference = rules?.riskProfile.drawdown.referenceBalance ?? null;
  const pending = overview?.resolution.pending ? 1 : 0;

  return (
    <>
      <HighlightBar
        icon={SlidersHorizontal}
        value={overview === null ? "—" : overview.guard.deferred ? "Différé" : "Immédiat"}
        label="à l'enregistrement"
        aside={
          <span className="text-xs text-panel-muted">
            {overview ? `évalué à ${clock(overview.evaluatedAt)}` : error ? "cœur injoignable" : "lecture…"}
          </span>
        }
      />
      <MetricPanel>
        <MetricPanelItem
          label="Compte réglé"
          value={account ? PROVIDER_NAMES[account.provider] : "—"}
          hint={account ? `${account.name} · ${account.login}` : "aucun compte enregistré"}
          icon={Landmark}
          solidIcon
        />
        <MetricPanelItem
          label="Capital de référence"
          value={rules === null ? "—" : reference === null ? "Non fixé" : formatCapital(reference)}
          tone={rules !== null && reference === null ? "warning" : undefined}
          hint={
            rules === null
              ? undefined
              : reference === null
                ? "perte max mesurée depuis le solde à la connexion"
                : "perte max mesurée depuis ce capital"
          }
          icon={ShieldCheck}
        />
        <MetricPanelItem
          label="Changement en attente"
          value={overview === null ? "—" : String(pending)}
          tone={pending > 0 ? "warning" : undefined}
          hint={pending > 0 ? "s'appliquera au prochain jour de trading" : "rien n'attend le prochain jour"}
          icon={Clock}
        />
        <MetricPanelItem
          label="Versions enregistrées"
          value={overview === null ? "—" : String(overview.versions.length)}
          hint="registre en ajout seul : rien ne s'efface"
          icon={History}
        />
      </MetricPanel>
    </>
  );
}
