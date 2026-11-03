/**
 * The editable part of an account's rules, as a form sees it: text in, rules out.
 *
 * Only numbers the trader sets are here — the limits of the Risk Engine (ADR 0015: *every value is set by the user, account by
 * account, none is « unlimited »*), the news window, the position limits and the cost the strategy tolerates. What this form
 * deliberately cannot reach is carried over untouched into whatever it saves: the autonomy ceiling of the account
 * (`executionProfile.maxMode`: raising it is a separate, explicit act), the trading windows, the symbols, and the FTMO challenge
 * with its objectives (a new challenge is a new account).
 *
 * The bounds are the core's own (`RiskProfile` and friends); the core re-checks all of them and has the last word — this only
 * saves a round trip for a typo.
 */

import type { AccountRules } from "@/lib/api/generated";

export type FieldId =
  | "referenceBalance"
  | "dailyLossLimitPercent"
  | "weeklyLossLimitPercent"
  | "maxDrawdownLimitPercent"
  | "maxRiskPerTradePercent"
  | "maxOpenRiskPercent"
  | "maxCorrelatedRiskPercent"
  | "maxTradesPerDay"
  | "maxConsecutiveLosses"
  | "consecutiveLossPauseMinutes"
  | "blackoutMinutes"
  | "maxOpenPositions"
  | "maxVolumePerOrder"
  | "costThreshold"
  | "commissionPerLotRoundTrip"
  | "maxSlippagePoints"
  | "commandTtlSeconds";

export type SectionId = "capital" | "risk" | "discipline" | "market" | "execution";

export interface FieldSpec {
  id: FieldId;
  section: SectionId;
  label: string;
  hint: string;
  unit?: string;
  integer: boolean;
  /** Exclusive lower bound when `minExclusive`, else inclusive. */
  min: number;
  minExclusive?: boolean;
  max?: number;
  /** Empty means « not set » (the core accepts null). */
  nullable?: boolean;
}

export const SECTIONS: Record<SectionId, { title: string; description: string }> = {
  capital: {
    title: "Capital et pertes maximales",
    description: "ce dont les limites de perte sont des pourcentages",
  },
  risk: {
    title: "Risque par trade et exposition",
    description: "ce que chaque trade, et l'ensemble des positions, peuvent engager",
  },
  discipline: {
    title: "Discipline",
    description: "le nombre de trades, la série de pertes et la pause qui suit",
  },
  market: {
    title: "Marché et positions",
    description: "la fenêtre des publications et le nombre de positions",
  },
  execution: {
    title: "Coût d'exécution",
    description: "ce que la stratégie tolère avant de ne pas prendre un trade",
  },
};

export const FIELDS: FieldSpec[] = [
  {
    id: "referenceBalance",
    section: "capital",
    label: "Capital de référence",
    hint: "Le capital engagé sur ce compte. Les limites de perte se calculent en pourcentage de ce montant, et le plancher s'en déduit. Vide : pas de référence fixe (le solde à la connexion fait foi).",
    unit: "$",
    integer: false,
    min: 1,
    max: 100_000_000,
    nullable: true,
  },
  {
    id: "dailyLossLimitPercent",
    section: "capital",
    label: "Perte journalière maximale",
    hint: "Au-delà, le compte est verrouillé jusqu'à ce que tu l'aies reconnu.",
    unit: "%",
    integer: false,
    min: 0,
    minExclusive: true,
    max: 100,
  },
  {
    id: "weeklyLossLimitPercent",
    section: "capital",
    label: "Perte hebdomadaire maximale",
    hint: "Mesurée depuis l'ouverture de la semaine (lundi 00:00, heure du courtier). Au-delà, plus aucune entrée jusqu'à la semaine suivante.",
    unit: "%",
    integer: false,
    min: 0,
    minExclusive: true,
    max: 100,
  },
  {
    id: "maxDrawdownLimitPercent",
    section: "capital",
    label: "Perte maximale totale",
    hint: "Mesurée depuis le capital de référence : c'est le plancher du compte.",
    unit: "%",
    integer: false,
    min: 0,
    minExclusive: true,
    max: 100,
  },
  {
    id: "maxRiskPerTradePercent",
    section: "risk",
    label: "Risque par trade",
    hint: "Ce que le stop d'un trade peut coûter. Le moteur de risque dimensionne la position à partir de lui.",
    unit: "%",
    integer: false,
    min: 0,
    minExclusive: true,
    max: 100,
  },
  {
    id: "maxOpenRiskPercent",
    section: "risk",
    label: "Risque ouvert maximal",
    hint: "La somme des risques de toutes les positions ouvertes.",
    unit: "%",
    integer: false,
    min: 0,
    minExclusive: true,
    max: 100,
  },
  {
    id: "maxCorrelatedRiskPercent",
    section: "risk",
    label: "Exposition corrélée maximale",
    hint: "Même devise, même sens, sur plusieurs positions (long EURUSD + long GBPUSD = short USD deux fois).",
    unit: "%",
    integer: false,
    min: 0,
    minExclusive: true,
    max: 100,
  },
  {
    id: "maxTradesPerDay",
    section: "discipline",
    label: "Trades par jour",
    hint: "Depuis le début de la journée de trading du compte.",
    integer: true,
    min: 1,
    max: 1_000,
  },
  {
    id: "maxConsecutiveLosses",
    section: "discipline",
    label: "Pertes consécutives",
    hint: "À cette série, le compte se met en pause.",
    integer: true,
    min: 1,
    max: 1_000,
  },
  {
    id: "consecutiveLossPauseMinutes",
    section: "discipline",
    label: "Pause après la série",
    hint: "À compter de la dernière perte. Une pause se termine d'elle-même.",
    unit: "min",
    integer: true,
    min: 1,
    max: 100_000,
  },
  {
    id: "blackoutMinutes",
    section: "market",
    label: "Fenêtre autour d'une publication",
    hint: "De part et d'autre de l'heure d'une publication du calendrier : aucune entrée.",
    unit: "min",
    integer: true,
    min: 0,
    max: 1_440,
  },
  {
    id: "maxOpenPositions",
    section: "market",
    label: "Positions ouvertes",
    hint: "Au total, tous symboles confondus. Aucune limite par symbole : un même symbole peut porter autant de positions simultanées que ce total, le risque ouvert et l'exposition corrélée le permettent.",
    integer: true,
    min: 1,
    max: 1_000,
  },
  {
    id: "maxVolumePerOrder",
    section: "market",
    label: "Volume maximal par ordre",
    hint: "En lots. Vide : seule la taille que le risque permet compte.",
    unit: "lots",
    integer: false,
    min: 0,
    minExclusive: true,
    max: 10_000,
    nullable: true,
  },
  {
    id: "costThreshold",
    section: "execution",
    label: "Seuil de coût (porte de coût S01)",
    hint: "Rapport coût / distance au stop au-dessus duquel S01 refuse un setup (0.25 : un quart).",
    integer: false,
    min: 0,
    minExclusive: true,
    max: 100,
  },
  {
    id: "commissionPerLotRoundTrip",
    section: "execution",
    label: "Commission aller-retour",
    hint: "Par lot, dans la devise du compte. 0 pour un compte Standard.",
    unit: "$/lot",
    integer: false,
    min: 0,
    max: 10_000,
  },
  {
    id: "maxSlippagePoints",
    section: "execution",
    label: "Glissement maximal",
    hint: "En points, toléré par l'agent à l'exécution.",
    unit: "pts",
    integer: true,
    min: 0,
    max: 100_000,
  },
  {
    id: "commandTtlSeconds",
    section: "execution",
    label: "Durée de vie d'une commande",
    hint: "Passé ce délai sans exécution, la commande expire (de 5 à 600 secondes).",
    unit: "s",
    integer: true,
    min: 5,
    max: 600,
  },
];

export const FIELDS_BY_ID = Object.fromEntries(FIELDS.map((field) => [field.id, field])) as Record<FieldId, FieldSpec>;

export type Draft = Record<FieldId, string>;

type Read = (rules: AccountRules) => number | null;

/** Where each field lives in the rules. */
const READ: Record<FieldId, Read> = {
  referenceBalance: (r) => r.riskProfile.drawdown.referenceBalance,
  dailyLossLimitPercent: (r) => r.riskProfile.drawdown.dailyLossLimitPercent,
  weeklyLossLimitPercent: (r) => r.riskProfile.drawdown.weeklyLossLimitPercent,
  maxDrawdownLimitPercent: (r) => r.riskProfile.drawdown.maxDrawdownLimitPercent,
  maxRiskPerTradePercent: (r) => r.riskProfile.maxRiskPerTradePercent,
  maxOpenRiskPercent: (r) => r.riskProfile.maxOpenRiskPercent,
  maxCorrelatedRiskPercent: (r) => r.riskProfile.maxCorrelatedRiskPercent,
  maxTradesPerDay: (r) => r.riskProfile.maxTradesPerDay,
  maxConsecutiveLosses: (r) => r.riskProfile.maxConsecutiveLosses,
  consecutiveLossPauseMinutes: (r) => r.riskProfile.consecutiveLossPauseMinutes,
  blackoutMinutes: (r) => r.riskProfile.news.blackoutMinutes,
  maxOpenPositions: (r) => r.riskProfile.positions.maxOpenPositions,
  maxVolumePerOrder: (r) => r.riskProfile.positions.maxVolumePerOrder,
  costThreshold: (r) => r.executionProfile.limits.costThreshold,
  commissionPerLotRoundTrip: (r) => r.executionProfile.limits.commissionPerLotRoundTrip,
  maxSlippagePoints: (r) => r.executionProfile.limits.maxSlippagePoints,
  commandTtlSeconds: (r) => r.executionProfile.limits.commandTtlSeconds,
};

type Write = (rules: AccountRules, value: number | null) => AccountRules;

const WRITE: Record<FieldId, Write> = {
  referenceBalance: (r, v) => ({
    ...r,
    riskProfile: { ...r.riskProfile, drawdown: { ...r.riskProfile.drawdown, referenceBalance: v } },
  }),
  dailyLossLimitPercent: (r, v) => ({
    ...r,
    riskProfile: { ...r.riskProfile, drawdown: { ...r.riskProfile.drawdown, dailyLossLimitPercent: v! } },
  }),
  weeklyLossLimitPercent: (r, v) => ({
    ...r,
    riskProfile: { ...r.riskProfile, drawdown: { ...r.riskProfile.drawdown, weeklyLossLimitPercent: v! } },
  }),
  maxDrawdownLimitPercent: (r, v) => ({
    ...r,
    riskProfile: { ...r.riskProfile, drawdown: { ...r.riskProfile.drawdown, maxDrawdownLimitPercent: v! } },
  }),
  maxRiskPerTradePercent: (r, v) => ({ ...r, riskProfile: { ...r.riskProfile, maxRiskPerTradePercent: v! } }),
  maxOpenRiskPercent: (r, v) => ({ ...r, riskProfile: { ...r.riskProfile, maxOpenRiskPercent: v! } }),
  maxCorrelatedRiskPercent: (r, v) => ({ ...r, riskProfile: { ...r.riskProfile, maxCorrelatedRiskPercent: v! } }),
  maxTradesPerDay: (r, v) => ({ ...r, riskProfile: { ...r.riskProfile, maxTradesPerDay: v! } }),
  maxConsecutiveLosses: (r, v) => ({ ...r, riskProfile: { ...r.riskProfile, maxConsecutiveLosses: v! } }),
  consecutiveLossPauseMinutes: (r, v) => ({ ...r, riskProfile: { ...r.riskProfile, consecutiveLossPauseMinutes: v! } }),
  blackoutMinutes: (r, v) => ({
    ...r,
    riskProfile: { ...r.riskProfile, news: { ...r.riskProfile.news, blackoutMinutes: v! } },
  }),
  maxOpenPositions: (r, v) => ({
    ...r,
    riskProfile: { ...r.riskProfile, positions: { ...r.riskProfile.positions, maxOpenPositions: v! } },
  }),
  maxVolumePerOrder: (r, v) => ({
    ...r,
    riskProfile: { ...r.riskProfile, positions: { ...r.riskProfile.positions, maxVolumePerOrder: v } },
  }),
  costThreshold: (r, v) => ({
    ...r,
    executionProfile: { ...r.executionProfile, limits: { ...r.executionProfile.limits, costThreshold: v! } },
  }),
  commissionPerLotRoundTrip: (r, v) => ({
    ...r,
    executionProfile: { ...r.executionProfile, limits: { ...r.executionProfile.limits, commissionPerLotRoundTrip: v! } },
  }),
  maxSlippagePoints: (r, v) => ({
    ...r,
    executionProfile: { ...r.executionProfile, limits: { ...r.executionProfile.limits, maxSlippagePoints: v! } },
  }),
  commandTtlSeconds: (r, v) => ({
    ...r,
    executionProfile: { ...r.executionProfile, limits: { ...r.executionProfile.limits, commandTtlSeconds: v! } },
  }),
};

/** The fields a form may offer for these rules: an FTMO challenge's capital is its size, fixed for its life. */
export function editableFields(rules: AccountRules): FieldSpec[] {
  return FIELDS.filter((field) => !(field.id === "referenceBalance" && rules.tradingRules.challenge !== null));
}

export function draftOf(rules: AccountRules): Draft {
  return Object.fromEntries(
    FIELDS.map((field) => {
      const value = READ[field.id](rules);
      return [field.id, value === null ? "" : String(value)];
    }),
  ) as Draft;
}

function parse(field: FieldSpec, text: string): { value: number | null } | { error: string } {
  const trimmed = text.trim();
  if (trimmed === "") {
    return field.nullable ? { value: null } : { error: `${field.label} : une valeur est requise.` };
  }
  const value = Number(trimmed.replace(",", "."));
  if (!Number.isFinite(value)) {
    return { error: `${field.label} : « ${trimmed} » n'est pas un nombre.` };
  }
  if (field.integer && !Number.isInteger(value)) {
    return { error: `${field.label} : un nombre entier est attendu.` };
  }
  const aboveMin = field.minExclusive ? value > field.min : value >= field.min;
  if (!aboveMin || (field.max !== undefined && value > field.max)) {
    const low = field.minExclusive ? `supérieur à ${field.min}` : `au moins ${field.min}`;
    return {
      error: `${field.label} : ${field.max !== undefined ? `${low} et ${field.max} au plus` : low}.`,
    };
  }
  return { value };
}

export type Applied = { rules: AccountRules; errors: [] } | { rules: null; errors: string[] };

/** The rules the draft describes — or why it does not describe any. Everything the form cannot edit is carried over as it was. */
export function applyDraft(base: AccountRules, draft: Draft): Applied {
  const errors: string[] = [];
  let rules = base;
  for (const field of editableFields(base)) {
    const parsed = parse(field, draft[field.id]);
    if ("error" in parsed) {
      errors.push(parsed.error);
    } else {
      rules = WRITE[field.id](rules, parsed.value);
    }
  }
  return errors.length > 0 ? { rules: null, errors } : { rules, errors: [] };
}

/** Whether the draft describes exactly the rules it started from. */
export function isUnchanged(base: AccountRules, draft: Draft): boolean {
  const original = draftOf(base);
  return editableFields(base).every((field) => {
    const a = parse(field, draft[field.id]);
    const b = parse(field, original[field.id]);
    return "value" in a && "value" in b ? a.value === b.value : draft[field.id].trim() === original[field.id].trim();
  });
}

/** The same rules once the user has written them: `configured` is what the autonomy precondition reads. */
export function withConfigured(rules: AccountRules, configured: boolean): AccountRules {
  return { ...rules, riskProfile: { ...rules.riskProfile, configured } };
}

export function readField(rules: AccountRules, id: FieldId): number | null {
  return READ[id](rules);
}

/** A value with its unit, the way a sentence says it: « 5 % », « 10000 $ », « non fixé ». */
export function formatField(field: FieldSpec, value: number | null): string {
  if (value === null) {
    return "non fixé";
  }
  return field.unit ? `${value} ${field.unit}` : String(value);
}

/**
 * What changing from one set of rules to another amounts to, one line per difference — for the history of an account and for a
 * change waiting for the next trading day. Includes what the form cannot edit (the autonomy ceiling, the « written by you »
 * flag, the challenge): if anything moved them, the history must say so.
 */
export function describeChange(from: AccountRules, to: AccountRules): string[] {
  const lines: string[] = [];
  for (const field of FIELDS) {
    const before = READ[field.id](from);
    const after = READ[field.id](to);
    if (before !== after) {
      lines.push(`${field.label} : ${formatField(field, before)} → ${formatField(field, after)}`);
    }
  }
  if (from.executionProfile.maxMode !== to.executionProfile.maxMode) {
    lines.push(`Plafond d'autonomie : ${from.executionProfile.maxMode} → ${to.executionProfile.maxMode}`);
  }
  if (from.riskProfile.configured !== to.riskProfile.configured) {
    lines.push(`Limites écrites par toi : ${from.riskProfile.configured ? "oui" : "non"} → ${to.riskProfile.configured ? "oui" : "non"}`);
  }
  const a = from.tradingRules.challenge;
  const b = to.tradingRules.challenge;
  if (JSON.stringify(a) !== JSON.stringify(b)) {
    lines.push("Challenge FTMO modifié");
  }
  return lines;
}
