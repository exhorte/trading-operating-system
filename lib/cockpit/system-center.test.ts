import { describe, expect, it } from "vitest";
import type { ConditionView, Mt5TerminalView, SystemCenterView } from "@/lib/api/generated";
import {
  authorizationLine,
  commandsFor,
  heartbeatLine,
  lightTone,
  openConditions,
  stateLabel,
  STATE_LABELS,
  summaryLine,
  verdictTone,
} from "./system-center";

const condition = (code: string, light: string): ConditionView => ({ code, label: code, light, detail: "", reasonCodes: [] });

const terminal = (changes: Partial<Mt5TerminalView["readiness"]> = {}): Mt5TerminalView =>
  ({
    terminal: {
      terminalId: "D0E8209F77C8CF37AD8BF550E51FF075",
      label: "exness-demo",
      installPath: "C:\\MT5",
      dataPath: "C:\\data",
      portable: false,
      declared: {
        accountId: null,
        expectedLogin: null,
        chartSymbol: null,
        chartPeriod: null,
        magic: null,
        allowedSymbols: [],
        provider: null,
        product: null,
      },
      deployment: null,
      operation: null,
      lastState: null,
      lastStateAt: null,
    },
    helloReceived: true,
    agent: null,
    readiness: {
      verdict: "READY",
      headerCode: null,
      redCodes: [],
      pendingCodes: [],
      warningCodes: [],
      conditions: [],
      executionAuthorization: { allowed: false, reasons: ["SYSTEM_MODE_OFF"] },
      ...changes,
    },
  }) as unknown as Mt5TerminalView;

const center = (terminals: Mt5TerminalView[], mode = "OFF"): SystemCenterView =>
  ({
    observedAt: "2026-11-12T12:00:00Z",
    coreStatus: "ok",
    executionMode: mode,
    agentsConnected: 1,
    mt5WorkersAlive: 1,
    terminals,
    unregisteredAgents: [],
    registryProblem: null,
    recentEvents: [],
  }) as SystemCenterView;

describe("tones", () => {
  it("is green only for READY, amber while validating, red when blocked", () => {
    expect(verdictTone("READY")).toBe("profit");
    expect(verdictTone("VALIDATING")).toBe("warning");
    expect(verdictTone("BLOCKED")).toBe("loss");
    expect(verdictTone("SOMETHING_NEW")).toBe("muted");
  });

  it("never turns an unknown light green", () => {
    expect(lightTone("GREEN")).toBe("profit");
    expect(lightTone("RED")).toBe("loss");
    expect(lightTone("PENDING")).toBe("warning");
    expect(lightTone("???")).toBe("muted");
  });
});

describe("states", () => {
  it("has a word for each state the launcher journals and says so when there is none", () => {
    expect(Object.keys(STATE_LABELS)).toHaveLength(12);
    expect(stateLabel("EA_READY")).toBe("Agent prêt");
    expect(stateLabel(null)).toBe("Aucun état journalisé");
    expect(stateLabel("FUTURE_STATE")).toBe("FUTURE_STATE");
  });

  it("has no state above ready — the launcher stops at the agent", () => {
    const words = Object.keys(STATE_LABELS).join(" ");
    expect(words).not.toMatch(/CONFIRM|ARMED|AUTONOMOUS/);
  });
});

describe("the authorization is a separate line", () => {
  it("says BLOCKED with its reasons even when the agent is READY", () => {
    const ready = terminal();
    expect(ready.readiness.verdict).toBe("READY");
    expect(authorizationLine(ready)).toBe("BLOQUÉE — SYSTEM_MODE_OFF");
  });

  it("says AUTORISÉE only when the core says allowed", () => {
    expect(authorizationLine(terminal({ executionAuthorization: { allowed: true, reasons: [] } }))).toBe("AUTORISÉE");
    expect(authorizationLine(terminal({ executionAuthorization: { allowed: false, reasons: [] } }))).toBe("BLOQUÉE");
  });
});

describe("conditions", () => {
  it("lists what is not green, red before pending, and never a green one", () => {
    const item = terminal({
      conditions: [condition("A", "GREEN"), condition("B", "PENDING"), condition("C", "RED"), condition("D", "GREEN")],
    });
    expect(openConditions(item).map((c) => c.code)).toEqual(["C", "B"]);
  });
});

describe("commands", () => {
  it("shows commands to copy — every one of them carries the terminal and none carries a secret", () => {
    const commands = commandsFor(terminal());
    expect(commands.length).toBeGreaterThanOrEqual(5);
    for (const { command } of commands) {
      expect(command).toContain("D0E8209F77C8CF37AD8BF550E51FF075");
      expect(command).not.toMatch(/password|token|--yes|--force/i);
    }
    expect(commands.find((c) => c.command.includes("start"))?.command).toContain("--dry-run");
  });
});

describe("words", () => {
  it("says the age of a heartbeat or that it is unknown", () => {
    expect(heartbeatLine(null)).toBe("inconnu");
    expect(heartbeatLine(undefined)).toBe("inconnu");
    expect(heartbeatLine(0.2)).toBe("à l'instant");
    expect(heartbeatLine(12.4)).toBe("il y a 12 s");
  });

  it("summarises the terminals and the mode — and says when there is none", () => {
    expect(summaryLine(center([]))).toContain("Aucun terminal enregistré");
    const line = summaryLine(center([terminal(), terminal({ verdict: "BLOCKED" })], "OBSERVE"));
    expect(line).toContain("2 terminal(aux)");
    expect(line).toContain("1 prêt(s)");
    expect(line).toContain("1 bloqué(s)");
    expect(line).toContain("OBSERVE");
  });
});
