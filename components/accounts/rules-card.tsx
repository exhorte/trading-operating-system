import { Scale } from "lucide-react";
import type { AccountProfile } from "@/lib/accounts/profile";
import { formatMoney } from "@/lib/format";
import { Panel } from "@/components/ui/panel";

function percentOf(reference: number | null, percent: number): string {
  return reference === null ? "sur le solde courant" : formatMoney((reference * percent) / 100);
}

/** The limits the risk engine applies to the account, in % and in money, with the reference they are measured from —
 *  the rules in force today, as the core resolved them. */
export function RulesCard({ profile }: { profile: AccountProfile }) {
  const { riskProfile: p, executionProfile } = profile.rules;
  const ref = profile.referenceBalance;
  const limits = executionProfile.limits;

  const rows: Array<[string, string, string]> = [
    ["Perte journalière max", `${p.drawdown.dailyLossLimitPercent} %`, percentOf(ref, p.drawdown.dailyLossLimitPercent)],
    ["Perte hebdomadaire max", `${p.drawdown.weeklyLossLimitPercent} %`, percentOf(ref, p.drawdown.weeklyLossLimitPercent)],
    [
      "Perte max",
      `${p.drawdown.maxDrawdownLimitPercent} %`,
      profile.floor === null ? "référence non fixée" : `plancher ${formatMoney(profile.floor)}`,
    ],
    ["Risque par trade", `${p.maxRiskPerTradePercent} %`, percentOf(ref, p.maxRiskPerTradePercent)],
    ["Risque ouvert max", `${p.maxOpenRiskPercent} %`, percentOf(ref, p.maxOpenRiskPercent)],
    ["Exposition corrélée max", `${p.maxCorrelatedRiskPercent} %`, percentOf(ref, p.maxCorrelatedRiskPercent)],
    ["Trades par jour", String(p.maxTradesPerDay), "—"],
    ["Pertes consécutives", String(p.maxConsecutiveLosses), `pause ${p.consecutiveLossPauseMinutes} min`],
    [
      "Positions ouvertes",
      String(p.positions.maxOpenPositions),
      `sans limite par symbole${p.positions.maxVolumePerOrder === null ? "" : ` · ${p.positions.maxVolumePerOrder} lot max`}`,
    ],
    ["Blackout publications", `±${p.news.blackoutMinutes} min`, "calendrier FRED"],
    ["Porte de coût S01", `c ≤ ${limits.costThreshold}`, "le spread se juge sur le coût, pas sur un plafond"],
  ];

  return (
    <Panel title="Règles appliquées" description="les limites du moteur de risque, en % et en montant" icon={Scale}>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="pb-2 font-medium">Règle</th>
            <th className="pb-2 text-right font-medium">Limite</th>
            <th className="pb-2 text-right font-medium">Montant</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([rule, limit, amount]) => (
            <tr key={rule} className="border-t">
              <td className="py-2 text-foreground">{rule}</td>
              <td className="tnum py-2 text-right text-foreground">{limit}</td>
              <td className="tnum py-2 text-right text-muted-foreground">{amount}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 border-t pt-4 text-sm">
        <dt className="text-muted-foreground">Référence de calcul</dt>
        <dd className={ref === null ? "text-warning" : "text-foreground"}>{profile.referenceSource}</dd>
        <dt className="text-muted-foreground">Commission</dt>
        <dd className="text-foreground">
          {limits.commissionPerLotRoundTrip > 0
            ? `${formatMoney(limits.commissionPerLotRoundTrip)} par lot, aller-retour`
            : "aucune (compte Standard mesuré en Phase 0)"}
        </dd>
        <dt className="text-muted-foreground">Plafond d&apos;autonomie</dt>
        <dd className="text-foreground">{executionProfile.maxMode} — jamais au-dessus, quoi que le cœur reçoive</dd>
        <dt className="text-muted-foreground">Limites écrites par toi</dt>
        <dd className={p.configured ? "text-foreground" : "text-warning"}>
          {p.configured ? "oui" : "pas encore — l'autonomie les exige (Settings)"}
        </dd>
      </dl>
    </Panel>
  );
}
