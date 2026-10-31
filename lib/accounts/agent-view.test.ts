import { describe, expect, it } from "vitest";
import { agent, snapshot } from "@/lib/realtime/test-fixtures";
import {
  accountKindLine,
  agentIdentityLine,
  foreignExpertsLine,
  haltLine,
  modeLine,
  permissionsLine,
} from "./agent-view";

const account = snapshot({
  accountId: "exness-477029930",
  server: "Exness-MT5Trial9",
  tradeMode: "demo",
  leverage: 2000,
  marginMode: "hedging",
  fifoClose: false,
  tradeAllowed: true,
});

const status = (overrides: Parameters<typeof agent>[0] = {}) =>
  agent({ accountLogin: "477029930", expertTradeAllowed: false, tradable: false, closable: false, ...overrides });

describe("accountKindLine", () => {
  it("says demo, server, leverage and hedging", () => {
    const line = accountKindLine(account);
    expect(line.state).toBe("Démo");
    expect(line.detail).toBe("serveur Exness-MT5Trial9 · levier 1:2000 · hedging");
  });

  it("flags a real account and an investor password", () => {
    const line = accountKindLine({ ...account, tradeMode: "real", marginMode: "netting", tradeAllowed: false });
    expect(line.state).toBe("RÉEL");
    expect(line.tone).toBe("warning");
    expect(line.detail).toContain("netting");
    expect(line.detail).toContain("mot de passe investisseur");
  });

  it("says when the terminal did not say rather than guessing", () => {
    const line = accountKindLine({ ...account, tradeMode: null });
    expect(line.state).toBe("Inconnu");
    expect(accountKindLine(null).state).toBe("—");
  });
});

describe("agentIdentityLine", () => {
  it("confirms the agent answers for the terminal's login", () => {
    expect(agentIdentityLine(status(), 477029930)).toMatchObject({ state: "477029930", tone: "profit" });
  });

  it("shows a preset expecting another login as a refusal", () => {
    const line = agentIdentityLine(status({ identity: "mismatch", expectedAccountId: "12345678" }), 477029930);
    expect(line.tone).toBe("loss");
    expect(line.detail).toContain("12345678");
  });

  it("shows an agent connected to no account at all as a refusal", () => {
    expect(agentIdentityLine(status({ identity: "no_account" }), 477029930)).toMatchObject({ state: "Refus", tone: "loss" });
  });

  it("shows an agent serving another login than the one the core is attached to", () => {
    expect(agentIdentityLine(status({ accountLogin: "999" }), 477029930).state).toBe("Écart");
  });

  it("says nothing is registered when there is no status", () => {
    expect(agentIdentityLine(null, 477029930).tone).toBe("muted");
  });
});

describe("permissionsLine", () => {
  it("counts the four permissions and names each", () => {
    const line = permissionsLine(status());
    expect(line.state).toBe("3/4");
    expect(line.detail).toContain("case de l'EA non");
  });

  it("does not invent permissions an agent does not publish", () => {
    const line = permissionsLine(
      status({ terminalTradeAllowed: null, expertTradeAllowed: null, accountTradeExpert: null, accountTradeAllowed: null }),
    );
    expect(line.state).toBe("—");
  });
});

describe("foreignExpertsLine / haltLine / modeLine", () => {
  it("warns about another expert that Algo Trading would arm too", () => {
    const line = foreignExpertsLine(status({ attachedExperts: ["Ultimate_ICT_Gold_Scalper_v4.0"] }));
    expect(line).toMatchObject({ state: "1", tone: "warning" });
    expect(line.detail).toContain("Ultimate_ICT_Gold_Scalper_v4.0");
  });

  it("is quiet when the agent is alone", () => {
    expect(foreignExpertsLine(status()).state).toBe("Aucun");
  });

  it("shows the halt", () => {
    expect(haltLine(status({ halted: true })).state).toBe("Posé");
    expect(haltLine(status()).state).toBe("Levé");
    expect(haltLine(null).state).toBe("—");
  });

  it("states the mode and this build's ceiling", () => {
    expect(modeLine(status()).detail).toContain("plafonne à observe");
    expect(modeLine(status({ modeCeiling: "confirm" })).detail).toBe("plafond de cette version : confirm");
  });
});
