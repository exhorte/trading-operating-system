/**
 * What the provider side of an account looks like on screen (ADR 0036) — pure, so it is tested without a browser.
 *
 * The core decides and explains; this module only *words* what it sends. A refusal is never shown as a bare red value: it carries the
 * core's stable reason code and a sentence that says what is wrong and what to do. A code this module does not know is shown as the
 * code itself, never swallowed.
 */

import type { AccountIdentification, EffectiveLimit, LimitSource, ProviderLossState } from "@/lib/api/generated";

/** The core's stable reason codes, in the trader's words. */
const REASONS: Record<string, string> = {
  // identification
  provider_not_identified: "Fournisseur non identifié : les noms que donne le terminal ne suffisent pas.",
  provider_ambiguous: "Fournisseur ambigu : les noms du terminal désignent plusieurs fournisseurs.",
  provider_mismatch: "Le fournisseur déclaré n'est pas celui que le terminal annonce.",
  environment_mismatch: "Démo ou réel : la déclaration n'est pas celle du terminal.",
  account_product_unknown: "Produit du compte inconnu : déclare-le (type et phase) avant que ce compte puisse trader.",
  provider_rules_unsourced: "Les limites de perte de ce produit ne sont pas sourcées : le compte ne peut pas trader dessous.",
  rules_profile_on_real_account: "Les règles d'un autre fournisseur ne se répètent que sur une démo, jamais sur un compte réel.",
  leverage_contradicts_product: "Le levier du terminal dépasse ce que le produit déclaré autorise.",
  account_facts_missing: "Le terminal n'a pas donné les faits du compte (serveur, société, levier ou devise).",
  // loss floors
  provider_daily_loss_breached: "Le plancher de perte quotidienne du fournisseur est atteint.",
  provider_max_loss_breached: "Le plancher de perte maximale du fournisseur est atteint.",
  provider_daily_reference_missing: "Le solde de référence de 00:00 n'est pas établi : aucune entrée tant qu'il ne l'est pas.",
  provider_daily_reference_stale: "Le solde de référence date d'un autre jour : il faut celui de 00:00 d'aujourd'hui.",
  provider_max_reference_incomplete: "L'historique des soldes de minuit est incomplet : le plafond glissant est inconnu.",
  provider_max_method_unsupported: "Ce plafond glissant n'est pas encore suivi par le cœur : entrées refusées par prudence.",
  provider_initial_capital_missing: "Aucun capital initial enregistré : les limites du fournisseur en sont un pourcentage.",
  provider_equity_unknown: "Aucune lecture de l'équité.",
  // market restrictions
  provider_news_restriction: "Publication restreinte par le fournisseur : aucune action d'ordre dans la fenêtre.",
  provider_news_calendar_unknown: "Le calendrier des publications restreintes n'est pas chargé : entrées refusées par prudence.",
  provider_news_symbol_unclassified: "Instrument non classé pendant une publication restreinte : bloqué dans le doute.",
  provider_overnight_restriction: "Une pause de marché de plus de 2 heures approche : ce produit doit être à plat avant.",
  provider_overnight_schedule_unknown: "Les horaires de pause du marché sont inconnus : entrées refusées par prudence.",
  provider_request_budget_exhausted: "Le budget de requêtes du jour est presque épuisé : plus d'entrée (une fermeture reste possible).",
  provider_request_count_unknown: "Le nombre de requêtes du jour n'est pas lisible.",
  instrument_specification_missing: "Le terminal n'a pas donné tout ce qu'il faut pour placer un ordre sur cet instrument.",
};

export function reasonText(code: string): string {
  return REASONS[code] ?? code;
}

const SOURCES: Record<LimitSource, string> = {
  personal: "Tes règles",
  provider: "Fournisseur",
  product: "Produit",
  instrument: "Instrument",
  market: "Marché",
  account: "État du compte",
};

export function sourceLabel(source: LimitSource): string {
  return SOURCES[source];
}

export type Tone = "profit" | "loss" | "warning" | "info" | "muted";

const CONFIDENCE: Record<AccountIdentification["providerConfidence"], { label: string; tone: Tone }> = {
  CONFIRMED: { label: "Confirmé", tone: "profit" },
  PROBABLE: { label: "Probable", tone: "info" },
  WEAK: { label: "Faible", tone: "warning" },
  CONFLICT: { label: "Conflit", tone: "loss" },
  NONE: { label: "Aucune identification", tone: "loss" },
};

export function confidenceView(confidence: AccountIdentification["providerConfidence"]): { label: string; tone: Tone } {
  return CONFIDENCE[confidence];
}

const MODES: Record<string, string> = {
  DEMO: "Démo",
  REAL: "Réel",
  SIMULATED: "Simulé (cotations réelles, fonds fictifs)",
};

export function modeLabel(mode: string | null): string {
  return mode === null ? "inconnu" : (MODES[mode] ?? mode);
}

const UNITS: Record<EffectiveLimit["unit"], (value: number) => string> = {
  percent: (value) => `${trimmed(value)} %`,
  count: (value) => `${Math.round(value)}`,
  lots: (value) => `${trimmed(value)} lot`,
  price: (value) => `${trimmed(value)}`,
};

function trimmed(value: number): string {
  return Number.parseFloat(value.toFixed(6)).toString();
}

/** « 3 % », « 15 », « — » when nothing bounds the limit. */
export function limitValue(limit: Pick<EffectiveLimit, "unit" | "value">): string {
  return limit.value === null ? "—" : UNITS[limit.unit](limit.value);
}

/** Where a limit comes from, in one line: who binds it, and what the other sources said. */
export function limitProvenance(limit: EffectiveLimit): string {
  if (limit.bindingSource === null) {
    return "aucune source ne la borne";
  }
  const others = limit.candidates
    .filter((candidate) => !(candidate.source === limit.bindingSource && candidate.value === limit.value))
    .map((candidate) => `${sourceLabel(candidate.source).toLowerCase()} ${UNITS[limit.unit](candidate.value)}`);
  const head = `${sourceLabel(limit.bindingSource)} — ${limit.bindingOrigin ?? ""}`.trim();
  return others.length > 0 ? `${head} · aussi : ${others.join(", ")}` : head;
}

/** The account currency, two decimals, thin-space thousands: « 97 000,00 USD ». */
export function money(value: number | null, currency: string): string {
  if (value === null) {
    return "inconnu";
  }
  return `${value.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

export interface LossLine {
  label: string;
  reference: string;
  floor: string;
  margin: string;
}

/** The two floors as table lines. A figure the core could not establish is « inconnu », never a zero. */
export function lossLines(state: ProviderLossState, currency: string): LossLine[] {
  if (state.status === "not_applicable") {
    return [];
  }
  const method = state.maxMethod === "trailing_eod_balance" ? "glissante, fin de journée" : state.maxMethod === "trailing_intraday_balance" ? "glissante, intrajournalière" : "statique";
  return [
    {
      label: `Perte quotidienne (${state.timezone ?? "?"}, 00:00)`,
      reference: money(state.dailyReferenceBalance, currency),
      floor: money(state.dailyFloor, currency),
      margin: money(state.dailyRemaining, currency),
    },
    {
      label: `Perte maximale (${method})`,
      reference: money(state.maxReferenceBalance, currency),
      floor: money(state.maxFloor, currency),
      margin: money(state.maxRemaining, currency),
    },
  ];
}

export function lossTone(state: ProviderLossState): Tone {
  switch (state.status) {
    case "ok":
      return "profit";
    case "breached":
      return "loss";
    case "unknown":
      return "warning";
    default:
      return "muted";
  }
}

export function lossStatusLabel(state: ProviderLossState): string {
  switch (state.status) {
    case "ok":
      return "Dans les limites";
    case "breached":
      return "Plancher atteint";
    case "unknown":
      return "Inconnu — entrées refusées";
    default:
      return "Aucun plancher";
  }
}
