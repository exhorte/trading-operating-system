import { describe, expect, it } from "vitest";
import {
  brokerMatchOverlap,
  DEFAULT_ACCOUNT_SETTINGS,
  describeGuardReason,
  isCancellable,
  isInEffect,
  nextDayAnchor,
  parseLedger,
  resolveAccountSettings,
  validateExnessSettings,
  validateFtmoSettings,
  versionStatus,
  type ExnessSettings,
  type FtmoSettings,
  type SettingsVersion,
} from "./settings";

const FTMO_25K: FtmoSettings = {
  challenge: { type: "2-step", accountSize: 25_000, phase: "challenge" },
  brokerMatch: "ftmo",
};

function ftmoVersion(
  versionId: string,
  requestedAt: string,
  options: Partial<Pick<SettingsVersion, "deferred" | "cancelledAt" | "dayStartedSince">> & {
    settings?: FtmoSettings;
  } = {},
): SettingsVersion {
  return {
    versionId,
    firm: "ftmo",
    settings: options.settings ?? FTMO_25K,
    requestedAt,
    deferred: options.deferred ?? false,
    deferralReasons: [],
    cancelledAt: options.cancelledAt ?? null,
    dayStartedSince: options.dayStartedSince ?? false,
  };
}

function exnessVersion(versionId: string, requestedAt: string, settings: ExnessSettings, deferred = false): SettingsVersion {
  return {
    versionId,
    firm: "exness",
    settings,
    requestedAt,
    deferred,
    deferralReasons: [],
    cancelledAt: null,
    dayStartedSince: false,
  };
}

// Exness's trading day of 2026-09-23 starts at 00:00 UTC (server GMT+0).
const TODAY = "2026-09-23T00:00:00.000Z";
const TOMORROW = "2026-09-24T00:00:00.000Z";

describe("isInEffect — a change applied at once, or deferred to the next trading day", () => {
  it("applies an immediate change as soon as it is written", () => {
    expect(isInEffect(ftmoVersion("v", "2026-09-23T10:00:00Z"), TODAY)).toBe(true);
  });

  it("keeps a deferred change out for the rest of the trading day it was requested in", () => {
    expect(isInEffect(ftmoVersion("v", "2026-09-23T10:00:00Z", { deferred: true }), TODAY)).toBe(false);
  });

  it("brings it in once a trading day has started after the request", () => {
    expect(isInEffect(ftmoVersion("v", "2026-09-23T10:00:00Z", { deferred: true }), TOMORROW)).toBe(true);
  });

  it("keeps a deferred change out while no anchor is known at all", () => {
    expect(isInEffect(ftmoVersion("v", "2026-09-20T10:00:00Z", { deferred: true }), null)).toBe(false);
  });

  it("never applies a cancelled change", () => {
    const cancelled = ftmoVersion("v", "2026-09-22T10:00:00Z", { cancelledAt: "2026-09-22T11:00:00Z" });
    expect(isInEffect(cancelled, TOMORROW)).toBe(false);
  });
});

describe("resolveAccountSettings", () => {
  it("falls back to the code's values while the ledger is empty", () => {
    const resolved = resolveAccountSettings([], TODAY);
    expect(resolved.settings).toEqual(DEFAULT_ACCOUNT_SETTINGS);
    expect(resolved.ftmo.source).toBeNull();
    expect(resolved.ftmo.pending).toBeNull();
  });

  it("applies the latest change in effect, per firm, independently", () => {
    const reference = { referenceBalance: 2_500, brokerMatch: "exness" };
    const resolved = resolveAccountSettings(
      [
        ftmoVersion("old", "2026-09-20T10:00:00Z", { settings: DEFAULT_ACCOUNT_SETTINGS.ftmo }),
        ftmoVersion("new", "2026-09-21T10:00:00Z"),
        exnessVersion("ex", "2026-09-19T10:00:00Z", reference),
      ],
      TODAY,
    );
    expect(resolved.settings.ftmo).toEqual(FTMO_25K);
    expect(resolved.ftmo.source?.versionId).toBe("new");
    expect(resolved.settings.exness).toEqual(reference);
  });

  // The anti-tilt case: two losses, the trader raises the challenge size to
  // widen the daily limit — the backend deferred it, today keeps the old one.
  it("keeps today's settings while a mid-session change waits for tomorrow", () => {
    const versions = [
      ftmoVersion("today", "2026-09-23T10:30:00Z", { deferred: true }),
      ftmoVersion("before", "2026-09-22T09:00:00Z", { settings: DEFAULT_ACCOUNT_SETTINGS.ftmo }),
    ];

    const now = resolveAccountSettings(versions, TODAY);
    expect(now.settings.ftmo.challenge.accountSize).toBe(10_000);
    expect(now.ftmo.source?.versionId).toBe("before");
    expect(now.ftmo.pending?.versionId).toBe("today");

    const tomorrow = resolveAccountSettings(versions, TOMORROW);
    expect(tomorrow.settings.ftmo.challenge.accountSize).toBe(25_000);
    expect(tomorrow.ftmo.pending).toBeNull();
  });

  it("does not report a cancelled change as pending", () => {
    const resolved = resolveAccountSettings(
      [ftmoVersion("x", "2026-09-23T10:30:00Z", { deferred: true, cancelledAt: "2026-09-23T10:31:00Z" })],
      TODAY,
    );
    expect(resolved.ftmo.pending).toBeNull();
    expect(resolved.settings.ftmo).toEqual(DEFAULT_ACCOUNT_SETTINGS.ftmo);
  });

  it("orders by request time whatever order the ledger arrives in", () => {
    const resolved = resolveAccountSettings(
      [ftmoVersion("a", "2026-09-20T10:00:00Z", { settings: DEFAULT_ACCOUNT_SETTINGS.ftmo }), ftmoVersion("b", "2026-09-21T10:00:00Z")],
      TODAY,
    );
    expect(resolved.ftmo.source?.versionId).toBe("b");
  });
});

describe("nextDayAnchor — the anchor never steps back within one account", () => {
  const exnessToday = { accountId: "477029930", startsAtUtc: TODAY };
  const exnessYesterday = { accountId: "477029930", startsAtUtc: "2026-09-22T00:00:00.000Z" };

  it("moves forward when a new day starts", () => {
    expect(nextDayAnchor(exnessYesterday, exnessToday)).toEqual(exnessToday);
  });

  // The race this exists for: the event published today's anchor, then a
  // read of /api/risk/today, served before the row was written, says yesterday.
  it("ignores a late read that would step back to the previous day", () => {
    expect(nextDayAnchor(exnessToday, exnessYesterday)).toEqual(exnessToday);
    expect(nextDayAnchor(exnessToday, { accountId: "477029930", startsAtUtc: null })).toEqual(exnessToday);
  });

  it("takes another account's anchor outright, even an earlier one", () => {
    const ftmo = { accountId: "511333949", startsAtUtc: "2026-09-22T22:00:00.000Z" };
    expect(nextDayAnchor(exnessToday, ftmo)).toEqual(ftmo);
  });

  it("takes the first reading there is", () => {
    expect(nextDayAnchor(null, exnessToday)).toEqual(exnessToday);
    expect(nextDayAnchor({ accountId: "477029930", startsAtUtc: null }, exnessToday)).toEqual(exnessToday);
  });
});

describe("versionStatus and isCancellable — the history rows", () => {
  const versions = [
    ftmoVersion("pending", "2026-09-23T10:30:00Z", { deferred: true }),
    ftmoVersion("current", "2026-09-22T09:00:00Z"),
    ftmoVersion("older", "2026-09-21T09:00:00Z"),
    ftmoVersion("withdrawn", "2026-09-20T09:00:00Z", { deferred: true, cancelledAt: "2026-09-20T09:05:00Z" }),
  ];
  const resolved = resolveAccountSettings(versions, TODAY);

  it("labels each version by where it stands today", () => {
    expect(versions.map((v) => versionStatus(v, resolved))).toEqual([
      "en_attente",
      "en_vigueur",
      "remplace",
      "annule",
    ]);
  });

  it("offers to withdraw only a pending change no trading day has run under", () => {
    expect(isCancellable(versions[0], "en_attente")).toBe(true);
    expect(isCancellable({ ...versions[0], dayStartedSince: true }, "en_attente")).toBe(false);
    expect(isCancellable(versions[1], "en_vigueur")).toBe(false);
  });
});

describe("parseLedger", () => {
  const raw = {
    versions: [
      {
        versionId: "v1",
        firm: "ftmo",
        settings: { challenge: { type: "2-step", accountSize: 25000, phase: "challenge" }, brokerMatch: "ftmo" },
        requestedAt: "2026-09-23T10:00:00.0000000Z",
        deferred: true,
        deferralReasons: [{ code: "trades_today", accountId: "477029930", count: 2, detail: null }],
        cancelledAt: null,
        dayStartedSince: false,
      },
      { versionId: "broken", firm: "ftmo", settings: { challenge: {} }, requestedAt: "x", deferred: false },
      { versionId: "unknown-firm", firm: "icmarkets", settings: {}, requestedAt: "2026-09-23T10:00:00Z", deferred: false },
    ],
    guard: { deferred: false, reasons: [] },
    evaluatedAt: "2026-09-23T10:00:05Z",
  };

  it("keeps the well-formed versions and drops the rest", () => {
    const ledger = parseLedger(raw);
    expect(ledger?.versions.map((v) => v.versionId)).toEqual(["v1"]);
    expect(ledger?.versions[0].deferralReasons[0].count).toBe(2);
    expect(ledger?.guard.deferred).toBe(false);
  });

  it("reads a guard with no explicit answer as deferred — the conservative reading", () => {
    expect(parseLedger({ ...raw, guard: {} })?.guard.deferred).toBe(true);
  });

  it("refuses what is not a ledger", () => {
    expect(parseLedger(null)).toBeNull();
    expect(parseLedger({ versions: "nope", guard: {} })).toBeNull();
  });
});

describe("describeGuardReason", () => {
  it("words each reason the backend can give", () => {
    expect(describeGuardReason({ code: "no_live_account", accountId: null, count: null, detail: null })).toContain(
      "Aucun compte n'est connecté",
    );
    expect(describeGuardReason({ code: "open_positions", accountId: "477029930", count: 1, detail: null })).toBe(
      "1 position ouverte sur le compte 477029930.",
    );
    expect(describeGuardReason({ code: "trades_today", accountId: "477029930", count: 3, detail: null })).toBe(
      "3 trades ouverts depuis le début de la journée de trading sur le compte 477029930.",
    );
    expect(
      describeGuardReason({ code: "active_lockout", accountId: "477029930", count: null, detail: "Kill switch" }),
    ).toBe("Verrou actif sur le compte 477029930 (Kill switch).");
  });
});

describe("validation — mirrors AccountSettingsValidation (C#)", () => {
  it("accepts the default settings", () => {
    expect(validateFtmoSettings(DEFAULT_ACCOUNT_SETTINGS.ftmo)).toEqual([]);
    expect(validateExnessSettings(DEFAULT_ACCOUNT_SETTINGS.exness)).toEqual([]);
  });

  it("refuses a size or a reference that would silently disable a loss gate", () => {
    expect(validateFtmoSettings({ ...FTMO_25K, challenge: { ...FTMO_25K.challenge, accountSize: 0 } })).toHaveLength(1);
    expect(validateFtmoSettings({ ...FTMO_25K, challenge: { ...FTMO_25K.challenge, accountSize: Number.NaN } })).toHaveLength(1);
    expect(validateExnessSettings({ referenceBalance: -1, brokerMatch: "exness" })).toHaveLength(1);
  });

  it("refuses a recognition text short enough to match any broker", () => {
    expect(validateFtmoSettings({ ...FTMO_25K, brokerMatch: " f " })).toHaveLength(1);
    expect(validateExnessSettings({ referenceBalance: null, brokerMatch: "" })).toHaveLength(1);
  });

  it("flags recognition texts that overlap", () => {
    expect(brokerMatchOverlap(DEFAULT_ACCOUNT_SETTINGS)).toBeNull();
    expect(
      brokerMatchOverlap({
        ftmo: { ...FTMO_25K, brokerMatch: "markets" },
        exness: { referenceBalance: null, brokerMatch: "Global Markets" },
      }),
    ).not.toBeNull();
  });
});
