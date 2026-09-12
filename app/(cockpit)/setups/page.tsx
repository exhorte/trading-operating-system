import { SetupProposalsPanel } from "@/components/cockpit/setup-proposals-panel";
import { ReconciliationView } from "@/components/cockpit/reconciliation-view";

/**
 * EA-02 — the instrument of measurement (S01, "Critère de réussite"). Not
 * a signal screen: no button here sends anything anywhere. See
 * context/product/tools/EA-02-observe-taux-accord.md.
 */
export default function SetupsPage() {
  return (
    <div className="flex flex-col gap-2">
      <SetupProposalsPanel />
      <ReconciliationView />
    </div>
  );
}
