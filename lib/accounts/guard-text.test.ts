import { describe, expect, it } from "vitest";
import { describeApplication, describeGuardReason, describeGuardReasons } from "./guard-text";

const reason = (code: string, extra: Partial<{ accountId: string; count: number; detail: string }> = {}) => ({
  code,
  accountId: extra.accountId ?? null,
  count: extra.count ?? null,
  detail: extra.detail ?? null,
});

describe("describeGuardReason", () => {
  it("words each reason the core can give", () => {
    expect(describeGuardReason(reason("no_live_account"))).toContain("Aucun compte n'est connecté");
    expect(describeGuardReason(reason("open_positions", { count: 1, accountId: "a1" }))).toBe(
      "1 position ouverte sur le compte a1.",
    );
    expect(describeGuardReason(reason("open_positions", { count: 3 }))).toBe("3 positions ouvertes.");
    expect(describeGuardReason(reason("trades_today", { count: 2, accountId: "a2" }))).toBe(
      "2 trades ouverts depuis le début de la journée de trading sur le compte a2.",
    );
    expect(describeGuardReason(reason("active_lockout", { accountId: "a1", detail: "Kill switch manuel" }))).toBe(
      "Verrou actif sur le compte a1 (Kill switch manuel).",
    );
  });

  it("does not hide a reason it does not know", () => {
    expect(describeGuardReason(reason("brand_new"))).toBe("Raison non reconnue : brand_new.");
  });
});

describe("describeApplication", () => {
  it("says whether a version applied at once, or waited, and why", () => {
    expect(describeApplication({ deferred: false, deferralReasons: [] })).toBe("appliqué immédiatement");
    expect(
      describeApplication({ deferred: true, deferralReasons: [reason("open_positions", { count: 1 }), reason("trades_today", { count: 1 })] }),
    ).toBe(
      "reporté au jour de trading suivant : 1 position ouverte. 1 trade ouvert depuis le début de la journée de trading.",
    );
    expect(describeGuardReasons([])).toBe("");
  });
});
