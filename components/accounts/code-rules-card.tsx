import { FTMO_COST_MODEL, ftmoRiskPolicy, type FtmoPhase } from "@/lib/accounts/ftmo";
import { REAL_COST_MODEL, realRiskPolicy } from "@/lib/accounts/real";
import { CONSECUTIVE_LOSS_PAUSE_MINUTES } from "@/lib/risk";
import { formatMoney } from "@/lib/format";
import { Card } from "@/components/ui/card";

/**
 * The rules themselves — not editable here, on purpose. FTMO's limits are
 * FTMO's (sourced from the trader's MetriX exports); Exness's 5 %/10 % and the
 * discipline limits are the trader's own decisions. Settings edits facts
 * about an account (which challenge, which capital); loosening a rule stays
 * a commit, reviewed like code (ADR 0007).
 */
export function CodeRulesCard({ ftmoPhase }: { ftmoPhase: FtmoPhase }) {
  const ftmo = ftmoRiskPolicy("display", ftmoPhase);
  const exness = realRiskPolicy("display");

  const rows: Array<[string, string, string]> = [
    ["Perte journalière max", `${ftmo.dailyLossLimitPercent} %`, `${exness.dailyLossLimitPercent} %`],
    ["Perte max", `${ftmo.maxDrawdownLimitPercent} %`, `${exness.maxDrawdownLimitPercent} %`],
    ["Risque par trade", `${ftmo.maxRiskPerTradePercent} %`, `${exness.maxRiskPerTradePercent} %`],
    ["Risque ouvert max", `${ftmo.maxOpenRiskPercent} %`, `${exness.maxOpenRiskPercent} %`],
    ["Trades par jour", String(ftmo.maxTradesPerDay), String(exness.maxTradesPerDay)],
    [
      `Pertes consécutives (pause ${CONSECUTIVE_LOSS_PAUSE_MINUTES} min)`,
      String(ftmo.maxConsecutiveLosses),
      String(exness.maxConsecutiveLosses),
    ],
    ["Spread max", `${ftmo.maxSpreadPoints} pts`, `${exness.maxSpreadPoints} pts`],
    ["Blackout publications", `±${ftmo.newsBlackoutMinutes} min`, `±${exness.newsBlackoutMinutes} min`],
    [
      "Commission (aller-retour)",
      `${formatMoney(FTMO_COST_MODEL.commissionPerLotRoundTrip)}/lot`,
      REAL_COST_MODEL.commissionPerLotRoundTrip > 0
        ? `${formatMoney(REAL_COST_MODEL.commissionPerLotRoundTrip)}/lot`
        : "aucune (Standard)",
    ],
  ];

  return (
    <Card title="Règles fixées dans le code">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-[10px] uppercase tracking-wider text-muted">
            <th className="pb-1 font-medium">Règle</th>
            <th className="pb-1 text-right font-medium">FTMO</th>
            <th className="pb-1 text-right font-medium">Exness</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([rule, ftmoValue, exnessValue]) => (
            <tr key={rule} className="border-t border-border">
              <td className="py-1.5 text-foreground">{rule}</td>
              <td className="tnum py-1.5 text-right text-foreground">{ftmoValue}</td>
              <td className="tnum py-1.5 text-right text-foreground">{exnessValue}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 border-t border-border pt-3 text-[11px] leading-snug text-muted">
        Pertes FTMO : règles de FTMO, sourcées par tes exports MetriX. Exness 5 %/10 % : ta décision
        du 2026-09-21. Le reste : tes limites de discipline, identiques partout. Modifiables par un
        commit uniquement (<code className="text-foreground">lib/accounts/ftmo.ts</code>,{" "}
        <code className="text-foreground">real.ts</code>) — ce sont des règles, pas des faits du compte.
      </p>
    </Card>
  );
}
