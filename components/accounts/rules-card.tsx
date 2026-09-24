import type { ActiveProfile } from "@/lib/accounts/active-profile";
import { CONSECUTIVE_LOSS_PAUSE_MINUTES } from "@/lib/risk";
import { formatMoney } from "@/lib/format";
import { Panel } from "@/components/ui/panel";

function percentOf(reference: number | null, percent: number): string {
  return reference === null ? "sur le solde courant" : formatMoney((reference * percent) / 100);
}

/** The limits the risk engine applies to the connected account, in % and in
 *  dollars, with the reference they are measured from (T12). */
export function RulesCard({ profile }: { profile: ActiveProfile }) {
  const { riskPolicy: p, referenceBalance: ref } = profile;
  const floor = ref === null ? null : ref - (ref * p.maxDrawdownLimitPercent) / 100;

  const rows: Array<[string, string, string]> = [
    ["Perte journalière max", `${p.dailyLossLimitPercent} %`, percentOf(ref, p.dailyLossLimitPercent)],
    [
      "Perte max",
      `${p.maxDrawdownLimitPercent} %`,
      floor === null ? "référence non fixée" : `plancher ${formatMoney(floor)}`,
    ],
    ["Risque par trade", `${p.maxRiskPerTradePercent} %`, percentOf(ref, p.maxRiskPerTradePercent)],
    ["Risque ouvert max", `${p.maxOpenRiskPercent} %`, percentOf(ref, p.maxOpenRiskPercent)],
    ["Trades par jour", String(p.maxTradesPerDay), "—"],
    [
      "Pertes consécutives",
      String(p.maxConsecutiveLosses),
      `pause ${CONSECUTIVE_LOSS_PAUSE_MINUTES} min`,
    ],
    ["Spread max", `${p.maxSpreadPoints} pts`, "—"],
    ["Blackout publications", `±${p.newsBlackoutMinutes} min`, "calendrier FRED"],
  ];

  return (
    <Panel title="Règles appliquées">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="pb-1 font-medium">Règle</th>
            <th className="pb-1 text-right font-medium">Limite</th>
            <th className="pb-1 text-right font-medium">Montant</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([rule, limit, amount]) => (
            <tr key={rule} className="border-t border-border">
              <td className="py-1.5 text-foreground">{rule}</td>
              <td className="tnum py-1.5 text-right text-foreground">{limit}</td>
              <td className="tnum py-1.5 text-right text-muted-foreground">{amount}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-t border-border pt-3 text-xs">
        <dt className="text-muted-foreground">Référence de calcul</dt>
        <dd className={ref === null ? "text-warning" : "text-foreground"}>{profile.referenceSource}</dd>
        <dt className="text-muted-foreground">Commission</dt>
        <dd className="text-foreground">
          {profile.costModel.commissionPerLotRoundTrip > 0
            ? `${formatMoney(profile.costModel.commissionPerLotRoundTrip)} par lot, aller-retour`
            : "aucune (compte Standard mesuré en Phase 0)"}
        </dd>
      </dl>
    </Panel>
  );
}
