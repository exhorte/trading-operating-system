import { describe, expect, it } from "vitest";
import type { PlanMode, StartupStageState, StartupStatus } from "@/lib/api/generated";
import {
  CHECK_LABELS,
  checkLabel,
  MODE_LABELS,
  MODE_RIGHTS,
  modeTone,
  REAL_ACCOUNT_BANNER,
  runLine,
  START_LABEL,
  STATE_LABELS,
  stateTone,
  verdictLine,
} from "./startup";

const status = (changes: Partial<StartupStatus> = {}): StartupStatus =>
  ({
    evaluatedAt: "2026-11-02T15:00:00Z",
    run: null,
    stages: [],
    checks: [],
    checksGreen: true,
    blockers: [],
    mode: "OBSERVE",
    planMode: "OBSERVE",
    rights: { mode: "OBSERVE", sendsOrders: false, needsHumanConfirmation: false, needsGreenReadiness: false, realMoney: false },
    ladder: [],
    ceiling: "OBSERVE",
    halted: false,
    haltedReason: null,
    entriesAuthorized: false,
    entriesReason: "",
    realAccount: false,
    realAccountBanner: null,
    account: null,
    canStart: true,
    nextAutomaticMode: null,
    canAuthorizeAutomatic: false,
    authorizeBlockers: [],
    ...changes,
  }) as StartupStatus;

describe("the fixed words", () => {
  it("keeps the labels of the mission word for word", () => {
    expect(START_LABEL).toBe("DÉMARRER LE SYSTÈME");
    expect(REAL_ACCOUNT_BANNER).toBe("COMPTE RÉEL — LES ORDRES PEUVENT ENTRAÎNER UNE PERTE FINANCIÈRE");
  });

  it("has a word and a tone for each of the seven states", () => {
    const states: StartupStageState[] = ["STOPPED", "STARTING", "READY", "RUNNING", "DEGRADED", "FAILED", "HALTED"];
    for (const state of states) {
      expect(STATE_LABELS[state]).toBeTruthy();
      expect(stateTone(state)).toBeTruthy();
    }
    expect(stateTone("FAILED")).toBe("loss");
    expect(stateTone("RUNNING")).toBe("profit");
    expect(stateTone("DEGRADED")).toBe("warning");
  });
});

describe("the modes of the plan", () => {
  const modes: PlanMode[] = ["OFF", "OBSERVE", "PAPER", "CONFIRM", "DEMO_AUTO", "LIVE_CONFIRM", "LIVE_AUTO", "HALTED"];

  it("names and describes every mode", () => {
    for (const mode of modes) {
      expect(MODE_LABELS[mode]).toContain(mode);
      expect(MODE_RIGHTS[mode].length).toBeGreaterThan(10);
    }
  });

  it("paints real money red and never calls an observation a trade", () => {
    expect(modeTone("LIVE_AUTO")).toBe("loss");
    expect(modeTone("LIVE_CONFIRM")).toBe("loss");
    expect(modeTone("OBSERVE")).toBe("info");
    expect(MODE_RIGHTS.OBSERVE).toContain("Aucun ordre");
    expect(MODE_RIGHTS.HALTED).toContain("fermer reste possible");
  });
});

describe("checks", () => {
  it("words the conditions of the mission, and falls back on the core's label", () => {
    expect(checkLabel("market_data_fresh", "x")).toBe("Données de marché fraîches");
    expect(checkLabel("brand_new_check", "From the core")).toBe("From the core");
    for (const id of ["heartbeat", "guardian_running", "no_unknown_commands", "risk_limits_loaded", "mode_authorized"]) {
      expect(CHECK_LABELS[id]).toBeTruthy();
    }
  });
});

describe("verdictLine", () => {
  it("says a position can be taken only when the core says so", () => {
    const line = verdictLine(
      status({
        entriesAuthorized: true,
        planMode: "DEMO_AUTO",
        rights: { mode: "DEMO_AUTO", sendsOrders: true, needsHumanConfirmation: false, needsGreenReadiness: true, realMoney: false },
      }),
    );
    expect(line).toContain("peut prendre des positions");
  });

  it("explains an observation, a stop and a missing condition", () => {
    expect(verdictLine(status())).toContain("ne prend pas de position");
    expect(verdictLine(status({ planMode: "OFF" }))).toContain("arrêté");
    expect(verdictLine(status({ halted: true }))).toContain("HALTED");
    const blocked = verdictLine(
      status({
        planMode: "CONFIRM",
        rights: { mode: "CONFIRM", sendsOrders: true, needsHumanConfirmation: true, needsGreenReadiness: false, realMoney: false },
        blockers: ["heartbeat", "market_data_fresh"],
      }),
    );
    expect(blocked).toBe("Aucune position ne sera prise : 2 conditions non remplies.");
  });
});

describe("runLine", () => {
  it("is nothing before a run, and says what happened after", () => {
    expect(runLine(status())).toBeNull();
    const run = {
      runId: "r",
      targetMode: "OBSERVE" as const,
      startedAt: "",
      finishedAt: null,
      currentStage: null,
      reachedMode: null,
      blockedOn: [] as string[],
    };
    expect(runLine(status({ run: { ...run, state: "RUNNING", message: "" } }))).toBe("Démarrage en cours…");
    expect(runLine(status({ run: { ...run, state: "BLOCKED", message: "no account" } }))).toBe("Démarrage bloqué : no account");
    expect(runLine(status({ run: { ...run, state: "PARTIAL", message: "held back" } }))).toContain("réserve");
    expect(runLine(status({ run: { ...run, state: "DONE", message: "running in OBSERVE" } }))).toBe("running in OBSERVE");
  });
});
