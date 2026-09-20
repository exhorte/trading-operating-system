/**
 * Account analysis — the sentence that goes with each table.
 *
 * The one thing FTMO's "Analyse de compte" does that none of our screens do:
 * every figure is accompanied by a plain sentence stating what it says. It
 * is the cheapest way to satisfy `explainable` in
 * `context/frontend/final_interface_spec.md`, and it is mechanical — these
 * are pure functions over the breakdowns, deterministic and testable.
 *
 * **What these sentences must never become.** FTMO's own text ends blocks
 * with advice like "focus only on those particular trades that turned out
 * successful for you". That is post-hoc candidate selection — precisely the
 * error that ended the edge research on 2026-09-04 (ADR 0002). These
 * sentences describe the sample and stop there. They never recommend
 * trading more of a bucket, less of another, or at a different hour. If a
 * sentence here ever starts with "tu devrais", it is a bug.
 */

import { formatSignedMoney } from "@/lib/format";
import {
  mostFrequent,
  worstBucket,
  type Bucket,
  type GeneralStats,
  type TradingDayStats,
} from "./breakdowns";

function plural(n: number, singular: string, pluralForm = `${singular}s`): string {
  return n === 1 ? `${n} ${singular}` : `${n} ${pluralForm}`;
}

/** Shared skeleton: how many buckets, which one dominates, which one costs. */
function describeBuckets(
  buckets: Bucket[],
  opts: { unitPlural: string; lead: (b: Bucket) => string },
): string {
  const top = mostFrequent(buckets);
  if (top === null) {
    return "Aucune donnée exploitable sur cette dimension pour la période retenue.";
  }

  const sentences = [
    `${plural(buckets.length, opts.unitPlural.replace(/s$/, ""), opts.unitPlural)} sur la période. ${opts.lead(top)}`,
  ];

  const worst = worstBucket(buckets);
  if (worst && worst.label !== top.label) {
    sentences.push(
      `Le plus coûteux est ${worst.label} : ${formatSignedMoney(worst.pnl)} sur ${plural(worst.trades, "trade")}.`,
    );
  }
  return sentences.join(" ");
}

export function describeDuration(buckets: Bucket[]): string {
  return describeBuckets(buckets, {
    unitPlural: "tranches de durée",
    lead: (b) =>
      `La plus fréquente est ${b.label}, avec ${plural(b.trades, "trade")} pour ${formatSignedMoney(b.pnl)}.`,
  });
}

export function describeSize(buckets: Bucket[]): string {
  return describeBuckets(buckets, {
    unitPlural: "tailles de position",
    lead: (b) =>
      `La plus utilisée est ${b.label} lot, avec ${plural(b.trades, "trade")} pour ${formatSignedMoney(b.pnl)}.`,
  });
}

export function describeOpenHour(buckets: Bucket[]): string {
  return describeBuckets(buckets, {
    unitPlural: "heures d'entrée",
    lead: (b) =>
      `La plus active est ${b.label} UTC, avec ${plural(b.trades, "trade")} pour ${formatSignedMoney(b.pnl)}.`,
  });
}

export function describeSymbol(buckets: Bucket[]): string {
  return describeBuckets(buckets, {
    unitPlural: "instruments",
    lead: (b) =>
      `Le plus traité est ${b.label}, avec ${plural(b.trades, "trade")} pour ${formatSignedMoney(b.pnl)}.`,
  });
}

/**
 * The one comparison worth spelling out: the same trades read by opening day
 * and by closing day. When the dominant day differs between the two, trades
 * are crossing midnight and a daily limit read on one of them is not reading
 * the other.
 */
export function describeDays(openDays: Bucket[], closeDays: Bucket[]): string {
  const topOpen = mostFrequent(openDays);
  const topClose = mostFrequent(closeDays);

  if (topOpen === null || topClose === null) {
    return "Aucune donnée exploitable sur cette dimension pour la période retenue.";
  }

  const base =
    `Au jour d'ouverture, ${topOpen.label.toLowerCase()} concentre ${plural(topOpen.trades, "trade")} ` +
    `pour ${formatSignedMoney(topOpen.pnl)}. Au jour de fermeture, c'est ${topClose.label.toLowerCase()} ` +
    `avec ${plural(topClose.trades, "trade")} pour ${formatSignedMoney(topClose.pnl)}.`;

  return topOpen.label === topClose.label
    ? `${base} Les deux lectures désignent le même jour : sur cette période, les positions ne traversent pas minuit.`
    : `${base} Les deux lectures divergent — au moins une position a été ouverte un jour et fermée le lendemain.`;
}

export function describeSide(buckets: Bucket[]): string {
  const buy = buckets.find((b) => b.label === "Achat");
  const sell = buckets.find((b) => b.label === "Vente");

  if (!buy && !sell) {
    return "Aucune donnée exploitable sur cette dimension pour la période retenue.";
  }
  if (!buy) {
    return `Uniquement des ventes sur la période : ${plural(sell!.trades, "trade")} pour ${formatSignedMoney(sell!.pnl)}. Aucun achat, donc rien à comparer.`;
  }
  if (!sell) {
    return `Uniquement des achats sur la période : ${plural(buy.trades, "trade")} pour ${formatSignedMoney(buy.pnl)}. Aucune vente, donc rien à comparer.`;
  }
  return (
    `${plural(buy.trades, "achat")} pour ${formatSignedMoney(buy.pnl)}, ` +
    `${plural(sell.trades, "vente")} pour ${formatSignedMoney(sell.pnl)}.`
  );
}

export function describeTradingDays(stats: TradingDayStats): string {
  if (stats.dayCount === 0) {
    return "Aucune séance clôturée sur la période retenue.";
  }

  const parts = [
    `Le solde a bougé sur ${plural(stats.dayCount, "séance")}, ` +
      `soit ${stats.avgTradesPerDay!.toFixed(1)} trades par séance en moyenne.`,
    `${plural(stats.positiveDays, "séance positive", "séances positives")}, ` +
      `${plural(stats.negativeDays, "séance négative", "séances négatives")}.`,
  ];

  if (stats.avgNegativeDay !== null) {
    parts.push(`La séance perdante moyenne vaut ${formatSignedMoney(stats.avgNegativeDay)}.`);
  }
  if (stats.avgPositiveDay !== null) {
    parts.push(`La séance gagnante moyenne vaut ${formatSignedMoney(stats.avgPositiveDay)}.`);
  }
  return parts.join(" ");
}

/**
 * The summary sentence. It states the sample size before anything else, and
 * says plainly when the sample is too small to read — a win rate over four
 * trades is a number, not a fact about the trader.
 */
export function describeGeneral(stats: GeneralStats): string {
  if (stats.tradeCount === 0) {
    return "Aucun trade clôturé sur la période retenue.";
  }

  const parts = [
    `${plural(stats.tradeCount, "trade")} clôturé${stats.tradeCount === 1 ? "" : "s"} ` +
      `pour ${formatSignedMoney(stats.netPnl)} net.`,
    `${stats.wins} gagnant${stats.wins === 1 ? "" : "s"}, ${stats.losses} perdant${stats.losses === 1 ? "" : "s"}` +
      (stats.breakeven > 0 ? `, ${stats.breakeven} à plat` : "") +
      ` — ${Math.round(stats.winRate * 100)} % de réussite.`,
  ];

  if (stats.avgWin !== null && stats.avgLoss !== null) {
    parts.push(
      `Gain moyen ${formatSignedMoney(stats.avgWin)}, perte moyenne ${formatSignedMoney(stats.avgLoss)}` +
        (stats.rewardRiskRatio !== null
          ? `, soit un rapport de ${stats.rewardRiskRatio.toFixed(2)}.`
          : "."),
    );
  }

  if (stats.tradeCount < 30) {
    parts.push(
      "Échantillon trop court pour qu'un de ces ratios dise quoi que ce soit du système : ce sont des faits sur la période, pas des propriétés stables.",
    );
  }
  return parts.join(" ");
}
