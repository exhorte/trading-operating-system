import { History } from "lucide-react";
import type { AccountRules, RuleVersionView, VersionStatus } from "@/lib/api/generated";
import { describeChange } from "@/lib/accounts/rules-draft";
import { describeApplication, VERSION_STATUS_LABELS } from "@/lib/accounts/guard-text";
import { Panel } from "@/components/ui/panel";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";
import { formatDateTime } from "./form-controls";

const STATUS_TONES: Record<VersionStatus, PillTone> = {
  in_effect: "profit",
  pending: "warning",
  superseded: "muted",
  cancelled: "muted",
};

/** The ledger, most recent first: what was asked, when, and whether it applied at once or waited for the next trading day —
 *  and why. Each version is shown against the one before it (the first, against the rules the account was registered with). */
export function SettingsHistory({
  versions,
  registeredRules,
}: {
  versions: RuleVersionView[];
  registeredRules: AccountRules;
}) {
  return (
    <Panel
      title="Historique des changements"
      description="ce qui a été demandé, quand, et s'il a pris effet tout de suite"
      icon={History}
      actions={<span className="text-sm text-muted-foreground">{versions.length} version(s)</span>}
    >
      {versions.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Aucun changement enregistré : les règles posées à l&apos;enregistrement du compte s&apos;appliquent.
        </p>
      ) : (
        <ul className="flex flex-col">
          {versions.map((version, index) => {
            const before = versions[index + 1]?.rules ?? registeredRules;
            const changes = describeChange(before, version.rules);
            return (
              <li key={version.versionId} className="border-t py-3 text-sm first:border-t-0 first:pt-0 last:pb-0">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-foreground">
                    {changes.length === 0 ? "Aucune différence avec la version précédente" : changes.join(" · ")}
                  </span>
                  <StatusPill tone={STATUS_TONES[version.status]}>{VERSION_STATUS_LABELS[version.status]}</StatusPill>
                </div>
                <p className="mt-1 text-sm leading-snug text-muted-foreground">
                  Demandé le {formatDateTime(version.requestedAt)} · {describeApplication(version)}
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
