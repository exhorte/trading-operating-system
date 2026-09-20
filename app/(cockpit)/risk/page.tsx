import { DisciplineGauge } from "@/components/cockpit/discipline-gauge";
import { LockoutHistory } from "@/components/cockpit/lockout-history";
import { RiskStatusPanel } from "@/components/cockpit/risk-status-panel";

/**
 * Risque & Discipline — « où en est ma discipline, et combien il me reste
 * avant le verrou ».
 *
 * Was an empty placeholder until 2026-09-20. The discipline score comes first
 * and the limits second, on purpose: the product is the process (ADR 0001),
 * so the compliance rate is the headline and the P&L does not appear on this
 * screen at all.
 *
 * Receives the live gate panel from the Command Center, and gives a screen to
 * two surfaces that had none — the compliance rate beyond its top-bar chip,
 * and the lockout history that GET /api/risk/lockouts has served since T07.
 */
export default function RiskPage() {
  return (
    <div className="flex flex-col gap-2">
      <div className="grid gap-2 lg:grid-cols-2">
        <DisciplineGauge />
        <RiskStatusPanel />
      </div>
      <LockoutHistory />
      <p className="text-xs text-muted">
        Le score de conformité porte sur les trades clôturés passés par ce système. Un ordre
        saisi directement dans MT5 y entre a posteriori, une fois la position fermée — il
        n&apos;a été contraint par aucune de ces limites au moment de son ouverture.
      </p>
    </div>
  );
}
