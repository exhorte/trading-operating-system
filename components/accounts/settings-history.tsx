import {
  describeGuardReason,
  describeVersion,
  versionStatus,
  type ResolvedAccountSettings,
  type SettingsVersion,
  type VersionStatus,
} from "@/lib/accounts/settings";
import { Panel } from "@/components/ui/panel";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";
import { formatDateTime } from "./form-controls";

const STATUS_PILLS: Record<VersionStatus, { tone: PillTone; label: string }> = {
  en_vigueur: { tone: "profit", label: "En vigueur" },
  en_attente: { tone: "warning", label: "En attente" },
  remplace: { tone: "muted", label: "Remplacé" },
  annule: { tone: "muted", label: "Annulé" },
};

/** The ledger, most recent first: what was asked, when, and whether it
 *  applied at once or waited for the next trading day — and why. */
export function SettingsHistory({
  versions,
  resolved,
}: {
  versions: SettingsVersion[];
  resolved: ResolvedAccountSettings;
}) {
  return (
    <Panel
      title="Historique des changements"
      actions={<span className="text-xs text-muted-foreground">{versions.length} version(s)</span>}
    >
      {versions.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          Aucun changement enregistré : les valeurs par défaut du code s&apos;appliquent.
        </p>
      ) : (
        <ul className="flex flex-col">
          {versions.map((version) => {
            const pill = STATUS_PILLS[versionStatus(version, resolved)];
            return (
              <li
                key={version.versionId}
                className="border-t border-border py-2 text-xs first:border-t-0 first:pt-0"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-foreground">
                    <span className="font-medium">{version.firm === "ftmo" ? "FTMO" : "Exness"}</span>
                    {" — "}
                    {describeVersion(version)}
                  </span>
                  <StatusPill tone={pill.tone}>{pill.label}</StatusPill>
                </div>
                <p className="mt-1 text-xs leading-snug text-muted-foreground">
                  Demandé le {formatDateTime(version.requestedAt)} ·{" "}
                  {version.deferred
                    ? `reporté au jour de trading suivant : ${version.deferralReasons
                        .map(describeGuardReason)
                        .join(" ")}`
                    : "appliqué immédiatement"}
                  {version.cancelledAt ? ` · annulé le ${formatDateTime(version.cancelledAt)}` : ""}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
