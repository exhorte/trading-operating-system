/**
 * Account settings (T12 incrément 2) — what the Settings screen edits, and
 * which version of it applies right now.
 *
 * Three things only, all facts about an account rather than rules: which
 * FTMO challenge is traded (type, size, phase), the capital an Exness
 * account's overall loss is measured from, and the text that recognises each
 * broker in the name MT5 reports. The percentages — FTMO's rules and the
 * trader's own discipline limits — stay in `ftmo.ts` / `real.ts`, changed by a
 * commit.
 *
 * The backend keeps every change in an append-only ledger and decides, when
 * the change is written, whether it applies at once or at the next trading
 * day (AccountSettingsGuard, C#). This module resolves the ledger against the
 * trading-day anchor of the account being traded — the same anchor T02a
 * already uses for the daily loss: a deferred change takes effect from the
 * first anchor that starts after it was requested.
 *
 * Nothing here is a credential. The terminal logs into the account; these
 * settings only describe it (ADR 0003).
 */

import { formatMoney } from "@/lib/format";
import type { BrokerMatchers, Firm } from "./firm";
import { ACTIVE_FTMO_CHALLENGE, type FtmoChallenge, type FtmoChallengeType, type FtmoPhase } from "./ftmo";
import { EXNESS_REFERENCE_BALANCE } from "./real";

export interface FtmoSettings {
  challenge: FtmoChallenge;
  /** Text searched, case-insensitively, in the broker name MT5 reports. */
  brokerMatch: string;
}

export interface ExnessSettings {
  /** The capital overall loss is measured from — null keeps the balance at
   *  cockpit connection, the behaviour every account had before T12. */
  referenceBalance: number | null;
  brokerMatch: string;
}

export interface AccountSettings {
  ftmo: FtmoSettings;
  exness: ExnessSettings;
}

/** What the code carries — in effect until the ledger holds a version. */
export const DEFAULT_ACCOUNT_SETTINGS: AccountSettings = {
  ftmo: { challenge: ACTIVE_FTMO_CHALLENGE, brokerMatch: "ftmo" },
  exness: { referenceBalance: EXNESS_REFERENCE_BALANCE, brokerMatch: "exness" },
};

export function brokerMatchersOf(settings: AccountSettings): BrokerMatchers {
  return { ftmo: settings.ftmo.brokerMatch, exness: settings.exness.brokerMatch };
}

// --- The ledger, as GET /api/account-settings returns it -------------------

/** Mirrors AccountSettingsGuard's codes (C#). */
export type GuardReasonCode = "no_live_account" | "open_positions" | "trades_today" | "active_lockout";

export interface GuardReason {
  code: string;
  accountId: string | null;
  count: number | null;
  detail: string | null;
}

/** The backend's answer to "if I save now, when does it apply?". */
export interface SettingsGuard {
  deferred: boolean;
  reasons: GuardReason[];
}

interface VersionBase {
  versionId: string;
  requestedAt: string;
  /** Requested mid-session: applies from the next trading-day anchor. */
  deferred: boolean;
  deferralReasons: GuardReason[];
  cancelledAt: string | null;
  /** A trading day has started since the request, on some account — the
   *  backend then refuses to cancel it (it may have governed a session). */
  dayStartedSince: boolean;
}

export type SettingsVersion =
  | (VersionBase & { firm: "ftmo"; settings: FtmoSettings })
  | (VersionBase & { firm: "exness"; settings: ExnessSettings });

export interface AccountSettingsLedger {
  /** Most recent first. */
  versions: SettingsVersion[];
  guard: SettingsGuard;
  evaluatedAt: string;
}

// --- Parsing: the page must not trust a shape it did not validate ----------

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseReason(value: unknown): GuardReason | null {
  if (!isObject(value) || typeof value.code !== "string") {
    return null;
  }
  return {
    code: value.code,
    accountId: typeof value.accountId === "string" ? value.accountId : null,
    count: typeof value.count === "number" ? value.count : null,
    detail: typeof value.detail === "string" ? value.detail : null,
  };
}

function parseReasons(value: unknown): GuardReason[] {
  return Array.isArray(value)
    ? value.map(parseReason).filter((r): r is GuardReason => r !== null)
    : [];
}

const CHALLENGE_TYPES: readonly FtmoChallengeType[] = ["1-step", "2-step"];
const PHASES: readonly FtmoPhase[] = ["challenge", "verification", "funded"];

function parseFtmoSettings(value: unknown): FtmoSettings | null {
  if (!isObject(value) || !isObject(value.challenge) || typeof value.brokerMatch !== "string") {
    return null;
  }
  const { type, accountSize, phase } = value.challenge;
  if (
    !CHALLENGE_TYPES.includes(type as FtmoChallengeType) ||
    !PHASES.includes(phase as FtmoPhase) ||
    typeof accountSize !== "number"
  ) {
    return null;
  }
  return {
    challenge: { type: type as FtmoChallengeType, accountSize, phase: phase as FtmoPhase },
    brokerMatch: value.brokerMatch,
  };
}

function parseExnessSettings(value: unknown): ExnessSettings | null {
  if (!isObject(value) || typeof value.brokerMatch !== "string") {
    return null;
  }
  const { referenceBalance } = value;
  if (referenceBalance !== null && typeof referenceBalance !== "number") {
    return null;
  }
  return { referenceBalance, brokerMatch: value.brokerMatch };
}

export function parseSettingsVersion(value: unknown): SettingsVersion | null {
  if (
    !isObject(value) ||
    typeof value.versionId !== "string" ||
    typeof value.requestedAt !== "string" ||
    typeof value.deferred !== "boolean"
  ) {
    return null;
  }
  const base: VersionBase = {
    versionId: value.versionId,
    requestedAt: value.requestedAt,
    deferred: value.deferred,
    deferralReasons: parseReasons(value.deferralReasons),
    cancelledAt: typeof value.cancelledAt === "string" ? value.cancelledAt : null,
    dayStartedSince: value.dayStartedSince === true,
  };
  if (value.firm === "ftmo") {
    const settings = parseFtmoSettings(value.settings);
    return settings ? { ...base, firm: "ftmo", settings } : null;
  }
  if (value.firm === "exness") {
    const settings = parseExnessSettings(value.settings);
    return settings ? { ...base, firm: "exness", settings } : null;
  }
  return null;
}

/** Null when the response is not a ledger at all. A malformed version is
 *  dropped rather than failing the whole read — the others still apply. */
export function parseLedger(value: unknown): AccountSettingsLedger | null {
  if (!isObject(value) || !Array.isArray(value.versions) || !isObject(value.guard)) {
    return null;
  }
  return {
    versions: value.versions
      .map(parseSettingsVersion)
      .filter((v): v is SettingsVersion => v !== null)
      .sort((a, b) => Date.parse(b.requestedAt) - Date.parse(a.requestedAt)),
    guard: {
      deferred: value.guard.deferred !== false,
      reasons: parseReasons(value.guard.reasons),
    },
    evaluatedAt: typeof value.evaluatedAt === "string" ? value.evaluatedAt : new Date().toISOString(),
  };
}

// --- Resolution --------------------------------------------------------------

/**
 * In effect for the account being traded: not cancelled, and either applied
 * at once or requested before the start of the current trading day. With no
 * anchor known (nothing connected yet), a deferred change is not in effect —
 * the conservative reading.
 */
export function isInEffect(version: SettingsVersion, currentAnchor: string | null): boolean {
  if (version.cancelledAt !== null) {
    return false;
  }
  if (!version.deferred) {
    return true;
  }
  return currentAnchor !== null && Date.parse(currentAnchor) > Date.parse(version.requestedAt);
}

/** A ledger entry already known to hold one firm's settings. */
export type VersionOf<S> = SettingsVersion & { settings: S };

export interface FirmResolution<S> {
  /** What applies right now. */
  settings: S;
  /** The ledger entry it comes from, or null when it is the code's default. */
  source: VersionOf<S> | null;
  /** The latest change still waiting for the next trading day, if any. */
  pending: VersionOf<S> | null;
}

export interface ResolvedAccountSettings {
  settings: AccountSettings;
  ftmo: FirmResolution<FtmoSettings>;
  exness: FirmResolution<ExnessSettings>;
}

function resolveFirm<S>(
  versions: SettingsVersion[],
  firm: Firm,
  currentAnchor: string | null,
  fallback: S,
): FirmResolution<S> {
  // Filtered on `firm`, so every entry holds this firm's settings.
  const own = versions
    .filter((v) => v.firm === firm)
    .sort((a, b) => Date.parse(b.requestedAt) - Date.parse(a.requestedAt)) as VersionOf<S>[];
  const source = own.find((v) => isInEffect(v, currentAnchor)) ?? null;
  const sourceAt = source ? Date.parse(source.requestedAt) : Number.NEGATIVE_INFINITY;
  const pending =
    own.find(
      (v) =>
        v.cancelledAt === null &&
        !isInEffect(v, currentAnchor) &&
        Date.parse(v.requestedAt) > sourceAt,
    ) ?? null;
  return { settings: source ? source.settings : fallback, source, pending };
}

/** Which version of each firm's settings applies, given the trading-day
 *  anchor of the account being traded. Pure. */
export function resolveAccountSettings(
  versions: SettingsVersion[],
  currentAnchor: string | null,
  defaults: AccountSettings = DEFAULT_ACCOUNT_SETTINGS,
): ResolvedAccountSettings {
  const ftmo = resolveFirm(versions, "ftmo", currentAnchor, defaults.ftmo);
  const exness = resolveFirm(versions, "exness", currentAnchor, defaults.exness);
  return { settings: { ftmo: ftmo.settings, exness: exness.settings }, ftmo, exness };
}

/** The trading-day anchor the resolution runs against, and whose it is. */
export interface DayAnchorState {
  accountId: string;
  startsAtUtc: string | null;
}

/**
 * The anchor to keep when a new reading arrives. Within one account it only
 * moves forward: a just-resolved anchor reaches the client in its
 * `risk.day_anchor.resolved` event before its row reaches the database (the
 * backend writes it asynchronously), so a read of /api/risk/today in that
 * window can return the previous day — which would put a change that just
 * took effect back into "pending". A different account replaces it outright:
 * its server clock may legitimately be hours behind (FTMO CE(S)T vs Exness
 * GMT). Pure.
 */
export function nextDayAnchor(current: DayAnchorState | null, incoming: DayAnchorState): DayAnchorState {
  if (!current || current.accountId !== incoming.accountId) {
    return incoming;
  }
  if (current.startsAtUtc === null) {
    return incoming;
  }
  if (incoming.startsAtUtc === null) {
    return current;
  }
  return Date.parse(incoming.startsAtUtc) >= Date.parse(current.startsAtUtc) ? incoming : current;
}

export type VersionStatus = "en_vigueur" | "en_attente" | "remplace" | "annule";

/** One row of the history: where this version stands today. */
export function versionStatus(
  version: SettingsVersion,
  resolved: ResolvedAccountSettings,
): VersionStatus {
  if (version.cancelledAt !== null) {
    return "annule";
  }
  const { source } = resolved[version.firm];
  if (source?.versionId === version.versionId) {
    return "en_vigueur";
  }
  if (source && Date.parse(version.requestedAt) < Date.parse(source.requestedAt)) {
    return "remplace";
  }
  return "en_attente";
}

/** Mirrors the backend's rule: a pending change can be withdrawn only while
 *  no trading day has started since it was requested, on any account. */
export function isCancellable(version: SettingsVersion, status: VersionStatus): boolean {
  return status === "en_attente" && version.deferred && !version.dayStartedSince;
}

// --- Wording -----------------------------------------------------------------

function plural(count: number, singular: string, pluralForm: string): string {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

export function describeGuardReason(reason: GuardReason): string {
  const account = reason.accountId ? ` sur le compte ${reason.accountId}` : "";
  const count = reason.count ?? 0;
  switch (reason.code) {
    case "no_live_account":
      return "Aucun compte n'est connecté : rien ne permet de vérifier qu'aucune position n'est ouverte.";
    case "open_positions":
      return `${plural(count, "position ouverte", "positions ouvertes")}${account}.`;
    case "trades_today":
      return `${plural(count, "trade ouvert", "trades ouverts")} depuis le début de la journée de trading${account}.`;
    case "active_lockout":
      return `Verrou actif${account}${reason.detail ? ` (${reason.detail})` : ""}.`;
    default:
      return `Raison non reconnue : ${reason.code}.`;
  }
}

const PHASE_LABELS: Record<FtmoPhase, string> = {
  challenge: "Challenge",
  verification: "Vérification",
  funded: "Funded",
};

export function describeFtmoSettings(settings: FtmoSettings): string {
  const { type, accountSize, phase } = settings.challenge;
  return (
    `${type === "2-step" ? "2-Step" : "1-Step"} · ${formatMoney(accountSize).replace(/\.00$/, "")} · ` +
    `${PHASE_LABELS[phase]} · reconnu par « ${settings.brokerMatch} »`
  );
}

export function describeExnessSettings(settings: ExnessSettings): string {
  const reference =
    settings.referenceBalance === null
      ? "capital de référence non fixé"
      : `capital de référence ${formatMoney(settings.referenceBalance).replace(/\.00$/, "")}`;
  return `${reference} · reconnu par « ${settings.brokerMatch} »`;
}

export function describeVersion(version: SettingsVersion): string {
  return version.firm === "ftmo"
    ? describeFtmoSettings(version.settings)
    : describeExnessSettings(version.settings);
}

// --- Validation: mirrors AccountSettingsValidation (C#) ---------------------

export const ACCOUNT_SIZE_BOUNDS = { min: 1_000, max: 10_000_000 } as const;
export const REFERENCE_BALANCE_BOUNDS = { min: 1, max: 100_000_000 } as const;
export const BROKER_MATCH_LENGTH = { min: 2, max: 64 } as const;

function brokerMatchError(brokerMatch: string): string | null {
  const length = brokerMatch.trim().length;
  return length < BROKER_MATCH_LENGTH.min || length > BROKER_MATCH_LENGTH.max
    ? `Le texte de reconnaissance doit faire de ${BROKER_MATCH_LENGTH.min} à ${BROKER_MATCH_LENGTH.max} caractères.`
    : null;
}

/** Empty when valid. */
export function validateFtmoSettings(settings: FtmoSettings): string[] {
  const errors: string[] = [];
  const size = settings.challenge.accountSize;
  if (!Number.isFinite(size) || size < ACCOUNT_SIZE_BOUNDS.min || size > ACCOUNT_SIZE_BOUNDS.max) {
    errors.push(
      `La taille du compte doit être comprise entre ${formatMoney(ACCOUNT_SIZE_BOUNDS.min)} et ${formatMoney(ACCOUNT_SIZE_BOUNDS.max)}.`,
    );
  }
  const matchError = brokerMatchError(settings.brokerMatch);
  if (matchError) {
    errors.push(matchError);
  }
  return errors;
}

/** Empty when valid. */
export function validateExnessSettings(settings: ExnessSettings): string[] {
  const errors: string[] = [];
  const reference = settings.referenceBalance;
  if (
    reference !== null &&
    (!Number.isFinite(reference) ||
      reference < REFERENCE_BALANCE_BOUNDS.min ||
      reference > REFERENCE_BALANCE_BOUNDS.max)
  ) {
    errors.push(
      `Le capital de référence doit être vide ou compris entre ${formatMoney(REFERENCE_BALANCE_BOUNDS.min)} et ${formatMoney(REFERENCE_BALANCE_BOUNDS.max)}.`,
    );
  }
  const matchError = brokerMatchError(settings.brokerMatch);
  if (matchError) {
    errors.push(matchError);
  }
  return errors;
}

/** Two recognition texts where one contains the other would send one firm's
 *  terminal to the other's rules — worth saying before it is saved. */
export function brokerMatchOverlap(settings: AccountSettings): string | null {
  const ftmo = settings.ftmo.brokerMatch.trim().toLowerCase();
  const exness = settings.exness.brokerMatch.trim().toLowerCase();
  if (!ftmo || !exness) {
    return null;
  }
  return ftmo.includes(exness) || exness.includes(ftmo)
    ? `Les textes « ${settings.ftmo.brokerMatch} » et « ${settings.exness.brokerMatch} » se recouvrent : un même nom de broker pourrait être reconnu comme l'un ou l'autre (FTMO est testé en premier).`
    : null;
}

export function sameFtmoSettings(a: FtmoSettings, b: FtmoSettings): boolean {
  return (
    a.challenge.type === b.challenge.type &&
    a.challenge.accountSize === b.challenge.accountSize &&
    a.challenge.phase === b.challenge.phase &&
    a.brokerMatch.trim() === b.brokerMatch.trim()
  );
}

export function sameExnessSettings(a: ExnessSettings, b: ExnessSettings): boolean {
  return a.referenceBalance === b.referenceBalance && a.brokerMatch.trim() === b.brokerMatch.trim();
}
