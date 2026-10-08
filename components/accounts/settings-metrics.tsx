import { Clock, History, Landmark, SlidersHorizontal, Trophy } from "lucide-react";
import { PHASE_LABELS, type AccountSettingsLedger, type ResolvedAccountSettings } from "@/lib/accounts/settings";
import { formatMoney } from "@/lib/format";
import { HighlightBar, MetricPanel, MetricPanelItem, MetricPanelList } from "@/components/ui/metric-panel";

const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });

const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });

/**
 * What is in force, and when a change would take effect, in the dark panel
 * (ADR 0017) — the « aperçu en direct » of a settings form. The headline is
 * the backend's own answer to « si j'enregistre maintenant, ça s'applique
 * quand ? » (AccountSettingsGuard): « Immédiat », or « Différé » to the next
 * trading day — displayed here, never computed here. Kept to one short word:
 * on a phone the headline shares its row with the label, and a longer one
 * was truncated to « Pro… ». Without a read ledger nothing is guessed:
 * dashes, and the reason.
 */
export function SettingsMetrics({
  ledger,
  error,
  resolved,
}: {
  ledger: AccountSettingsLedger | null;
  error: string | null;
  resolved: ResolvedAccountSettings;
}) {
  const { ftmo, exness } = resolved;
  const challenge = ftmo.settings.challenge;
  const reference = exness.settings.referenceBalance;
  const pending = [ftmo.pending, exness.pending].filter((version) => version !== null).length;
  const sourceLabel = (source: { requestedAt: string } | null) =>
    source ? `configuré le ${shortDate(source.requestedAt)}` : "défaut du code";

  return (
    <>
      <HighlightBar
        icon={SlidersHorizontal}
        value={ledger === null ? "—" : ledger.guard.deferred ? "Différé" : "Immédiat"}
        label="à l'enregistrement"
        aside={
          <span className="text-xs text-panel-muted">
            {ledger ? `évalué à ${clock(ledger.evaluatedAt)}` : error ? "backend injoignable" : "lecture…"}
          </span>
        }
      />
      <MetricPanel>
        <MetricPanelItem
          label="Challenge FTMO"
          value={challenge.type === "2-step" ? "2-Step" : "1-Step"}
          hint={`${formatMoney(challenge.accountSize).replace(/\.00$/, "")} · ${PHASE_LABELS[challenge.phase]} · ${sourceLabel(ftmo.source)}`}
          icon={Trophy}
        />
        <MetricPanelItem
          label="Capital de référence Exness"
          value={reference === null ? "Non fixé" : formatMoney(reference).replace(/\.00$/, "")}
          tone={reference === null ? "warning" : undefined}
          hint={
            reference === null
              ? "perte max mesurée depuis le solde à la connexion"
              : `perte max mesurée depuis ce capital · ${sourceLabel(exness.source)}`
          }
          icon={Landmark}
        />
        <MetricPanelItem
          label="Changement en attente"
          value={ledger === null ? "—" : String(pending)}
          tone={pending > 0 ? "warning" : undefined}
          hint={pending > 0 ? "s'appliquera au prochain jour de trading" : "rien n'attend le prochain jour"}
          icon={Clock}
          solidIcon
        />
        <MetricPanelItem
          label="Versions enregistrées"
          value={ledger === null ? "—" : String(ledger.versions.length)}
          hint="registre en ajout seul : rien ne s'efface"
          icon={History}
        />
        <MetricPanelList
          items={[
            { label: "Reconnaissance FTMO", value: `« ${ftmo.settings.brokerMatch} »` },
            { label: "Reconnaissance Exness", value: `« ${exness.settings.brokerMatch} »` },
          ]}
        />
      </MetricPanel>
    </>
  );
}
