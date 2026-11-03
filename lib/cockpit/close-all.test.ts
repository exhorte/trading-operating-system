import { describe, expect, it } from "vitest";
import type { CloseAllCounts, CloseAllItem, CloseAllReport } from "@/lib/api/generated";
import {
  actionText,
  BUTTON_LABEL,
  CONFIRM_LABEL,
  CONFIRMATION,
  headline,
  ITEM_LABELS,
  itemTone,
  nextStep,
  progressLine,
  reasonLine,
  reasonText,
  summary,
} from "./close-all";

const counts = (changes: Partial<CloseAllCounts> = {}): CloseAllCounts => ({
  detected: 0,
  confirmed: 0,
  inProgress: 0,
  verifying: 0,
  alreadyClosed: 0,
  rejected: 0,
  simulated: 0,
  unknown: 0,
  mismatch: 0,
  notClosable: 0,
  positionsStillOpen: 0,
  ordersStillPending: 0,
  ...changes,
});

const item = (status: CloseAllItem["status"], changes: Partial<CloseAllItem> = {}): CloseAllItem => ({
  target: "position",
  targetId: "101",
  symbol: "EURUSDm",
  side: "buy",
  volume: 0.1,
  commandId: "ca-batch000001-101",
  commandState: null,
  status,
  rejectCode: null,
  detail: "",
  stillOpen: false,
  ...changes,
});

const report = (changes: Partial<CloseAllReport> = {}): CloseAllReport => ({
  batchId: "batch000001",
  accountId: "acc",
  status: "IN_PROGRESS",
  final: false,
  startedAt: "2026-11-02T15:00:00Z",
  evaluatedAt: "2026-11-02T15:00:05Z",
  includePendingOrders: false,
  items: [],
  counts: counts(),
  failures: [],
  actions: [],
  reconciled: false,
  reconciliationCritical: 0,
  snapshotFresh: true,
  otherOpenPositions: [],
  simulatedOnly: false,
  ...changes,
});

describe("the words the trader must read exactly", () => {
  it("keeps the two labels the mission asked for, word for word", () => {
    expect(BUTTON_LABEL).toBe("FERMER TOUTES LES POSITIONS");
    expect(CONFIRM_LABEL).toBe("CONFIRMER LA FERMETURE DE TOUTES LES POSITIONS");
  });

  it("sends the confirmation the core demands", () => {
    expect(CONFIRMATION).toBe("CLOSE_ALL");
  });

  it("has a sentence for every status of an item, and none says closed unless it is confirmed", () => {
    for (const [status, label] of Object.entries(ITEM_LABELS)) {
      expect(label.length).toBeGreaterThan(3);
      if (status !== "CONFIRMED" && status !== "ALREADY_CLOSED") {
        expect(label.toLowerCase()).not.toMatch(/^fermée/);
      }
    }
    expect(ITEM_LABELS.SIMULATED).toContain("rien n'a été fermé");
  });
});

describe("headline", () => {
  it("only says everything is closed when the core says COMPLETE", () => {
    expect(headline("COMPLETE")).toContain("réconciliées avec MT5");
    expect(headline("AWAITING_RECONCILIATION")).toContain("réconciliation");
    expect(headline("AWAITING_RECONCILIATION")).not.toContain("Toutes les positions sont fermées");
    expect(headline("INCOMPLETE")).toContain("incomplète");
    expect(headline("NOTHING_TO_CLOSE")).toBe("Aucune position à fermer.");
  });
});

describe("progressLine", () => {
  it("lists what is not zero, in the order of the mission", () => {
    const line = progressLine(
      report({ counts: counts({ detected: 3, confirmed: 1, inProgress: 1, rejected: 1 }) }),
    );
    expect(line).toBe("3 cibles détectées · 1 fermeture confirmée · 1 en cours · 1 refusée");
  });

  it("pluralises and never prints a zero", () => {
    const line = progressLine(report({ counts: counts({ detected: 2, confirmed: 2 }) }));
    expect(line).toBe("2 cibles détectées · 2 fermetures confirmées");
    expect(line).not.toContain("0");
  });

  it("names the simulated and the not closable", () => {
    const line = progressLine(report({ counts: counts({ detected: 2, simulated: 1, notClosable: 1 }) }));
    expect(line).toContain("1 simulée");
    expect(line).toContain("1 non fermable par l'agent");
  });
});

describe("summary", () => {
  it("counts as closed only what is confirmed or was already gone", () => {
    const s = summary(
      report({
        counts: counts({
          detected: 6,
          confirmed: 2,
          alreadyClosed: 1,
          rejected: 1,
          unknown: 1,
          simulated: 1,
          positionsStillOpen: 3,
        }),
      }),
    );
    expect(s).toEqual({ closed: 3, stillOpen: 3, rejectedOrUnknown: 3 });
  });
});

describe("nextStep", () => {
  it("polls while a command is moving, asks the core to verify once they have all settled, and stops when final", () => {
    expect(nextStep(report({ items: [item("IN_PROGRESS")] }))).toBe("poll");
    expect(nextStep(report({ items: [item("CONFIRMED")], status: "AWAITING_RECONCILIATION" }))).toBe("verify");
    expect(nextStep(report({ items: [item("VERIFYING")], status: "IN_PROGRESS" }))).toBe("verify");
    expect(nextStep(report({ final: true, status: "COMPLETE" }))).toBe("stop");
  });
});

describe("texts", () => {
  it("tones: a refusal is red, a doubt is not green, a confirmation is green", () => {
    expect(itemTone("CONFIRMED")).toBe("profit");
    expect(itemTone("REJECTED")).toBe("loss");
    expect(itemTone("MISMATCH")).toBe("loss");
    expect(itemTone("UNKNOWN")).toBe("warning");
    expect(itemTone("SIMULATED")).toBe("warning");
    expect(itemTone("IN_PROGRESS")).toBe("info");
  });

  it("explains the reject codes it knows and falls back on the core's own words", () => {
    expect(reasonText("TARGET_NOT_OURS")).toContain("numéro magique");
    expect(reasonText("SOMETHING_NEW", "the broker said no")).toBe("SOMETHING_NEW — the broker said no");
  });

  it("words every recommended action and never tells to resend an unknown command", () => {
    expect(actionText("RECONCILE")).toContain("Ne la renvoyez jamais");
    expect(actionText("CLOSE_IN_MT5")).toContain("MT5");
    expect(actionText("ENABLE_AGENT")).toContain("aucun ordre n'a atteint le courtier");
  });

  it("uses its own words for a known warning and the core's sentence for an unknown one", () => {
    expect(reasonLine({ code: "market_price", detail: "x" }, "warning")).toContain("prix disponible");
    expect(reasonLine({ code: "no_agent", detail: "x" }, "blocker")).toContain("Aucun agent");
    expect(reasonLine({ code: "brand_new", detail: "the core's sentence" }, "warning")).toBe("the core's sentence");
    expect(reasonLine({ code: "real_account", detail: "x" }, "warning")).toBe(
      "COMPTE RÉEL — LES ORDRES PEUVENT ENTRAÎNER UNE PERTE FINANCIÈRE",
    );
  });
});
