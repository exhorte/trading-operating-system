import { describe, expect, it } from "vitest";
import type { JournalTrade } from "@/lib/journal/types";
import { ftmoObjectives, ftmoRiskPolicy, type FtmoChallenge } from "./ftmo";
import { evaluateFtmoObjectives, type ObjectivesInput } from "./objectives";

const challenge: FtmoChallenge = { type: "2-step", accountSize: 10_000, phase: "challenge" };

function trade(overrides: Partial<JournalTrade> = {}): JournalTrade {
  return {
    brokerPositionId: "1",
    symbol: "XAUUSD",
    side: "sell",
    volume: 0.2,
    entryPrice: 2400,
    exitPrice: 2401,
    realizedPnl: -20,
    stopLoss: 2410,
    openedAt: "2026-07-15T12:00:00Z",
    closedAt: "2026-07-15T12:01:00Z",
    hasCapture: false,
    ...overrides,
  };
}

function input(overrides: Partial<ObjectivesInput> = {}): ObjectivesInput {
  return {
    challenge,
    policy: ftmoRiskPolicy("acc", "challenge"),
    trades: [],
    balance: 10_000,
    equity: 10_000,
    ...overrides,
  };
}

function row(rows: ReturnType<typeof evaluateFtmoObjectives>, key: string) {
  return rows.find((r) => r.key === key)!;
}

describe("ftmoObjectives", () => {
  it("is sourced for the 2-Step challenge phase (MetriX exports)", () => {
    expect(ftmoObjectives(challenge)).toEqual({ minTradingDays: 4, profitTargetPercent: 10 });
  });

  it("guesses nothing for phases the exports never showed", () => {
    expect(ftmoObjectives({ ...challenge, phase: "verification" })).toEqual({
      minTradingDays: null,
      profitTargetPercent: null,
    });
  });
});

describe("evaluateFtmoObjectives", () => {
  it("lists the four objectives in MetriX's order", () => {
    expect(evaluateFtmoObjectives(input()).map((r) => r.key)).toEqual([
      "min_days",
      "daily_loss",
      "max_loss",
      "profit_target",
    ]);
  });

  // The real outcome of challenge 511333949, from the MetriX export
  // ("Résumé quotidien"): 15/07 −369.30, 16/07 −99.96, 17/07 −289.04,
  // 20/07 −245.58 — summing to the report's −1 003.88 $, final balance
  // 8 996.12 $. FTMO's verdict: "Admis" on days and daily loss, "Perte
  // dépassée" on the overall limit, "Non admis" on the target.
  it("reproduces FTMO's own verdict on challenge 511333949", () => {
    const rows = evaluateFtmoObjectives(
      input({
        balance: 8_996.12,
        equity: 8_996.12,
        trades: [
          trade({ openedAt: "2026-07-20T12:00:00Z", closedAt: "2026-07-20T12:02:00Z", realizedPnl: -245.58 }),
          trade({ openedAt: "2026-07-15T12:00:00Z", closedAt: "2026-07-15T12:02:00Z", realizedPnl: -369.3 }),
          trade({ openedAt: "2026-07-16T12:00:00Z", closedAt: "2026-07-16T12:02:00Z", realizedPnl: -99.96 }),
          trade({ openedAt: "2026-07-17T12:00:00Z", closedAt: "2026-07-17T12:02:00Z", realizedPnl: -289.04 }),
        ],
      }),
    );
    expect(row(rows, "min_days")).toMatchObject({ result: "4 jours", state: "atteint" });
    expect(row(rows, "daily_loss")).toMatchObject({ state: "respecte" });
    expect(row(rows, "daily_loss").result).toContain("-$369.30");
    expect(row(rows, "max_loss").state).toBe("depasse");
    expect(row(rows, "profit_target").state).toBe("en_cours");
  });

  it("counts distinct opening days, not trades", () => {
    const rows = evaluateFtmoObjectives(
      input({
        trades: [
          trade({ openedAt: "2026-07-15T09:00:00Z" }),
          trade({ openedAt: "2026-07-15T15:00:00Z" }),
          trade({ openedAt: "2026-07-16T09:00:00Z" }),
        ],
      }),
    );
    expect(row(rows, "min_days")).toMatchObject({ result: "2 jours", state: "en_cours" });
  });

  it("falls back to the close for a trade with no recorded opening, and says so", () => {
    const rows = evaluateFtmoObjectives(input({ trades: [trade({ openedAt: null })] }));
    expect(row(rows, "min_days").result).toBe("1 jour");
    expect(row(rows, "min_days").note).toContain("1 trade(s) sans ouverture enregistrée");
  });

  it("sums a day's closes before judging the daily limit", () => {
    const rows = evaluateFtmoObjectives(
      input({
        trades: [
          trade({ closedAt: "2026-07-15T10:00:00Z", realizedPnl: -300 }),
          trade({ closedAt: "2026-07-15T14:00:00Z", realizedPnl: -250 }),
        ],
      }),
    );
    expect(row(rows, "daily_loss").state).toBe("depasse");
  });

  it("judges the overall limit on the lower of balance and equity", () => {
    const open = evaluateFtmoObjectives(input({ balance: 9_500, equity: 8_950 }));
    expect(row(open, "max_loss").state).toBe("depasse");

    const safe = evaluateFtmoObjectives(input({ balance: 9_500, equity: 9_400 }));
    expect(row(safe, "max_loss")).toMatchObject({ state: "respecte" });
    expect(row(safe, "max_loss").result).toContain("$400.00");
  });

  it("reaches the profit target on the balance only", () => {
    expect(row(evaluateFtmoObjectives(input({ balance: 11_000 })), "profit_target").state).toBe(
      "atteint",
    );
    // Open profit does not count until closed.
    expect(
      row(evaluateFtmoObjectives(input({ balance: 10_500, equity: 11_200 })), "profit_target").state,
    ).toBe("en_cours");
  });

  it("marks unsourced rules as such instead of inventing them", () => {
    const rows = evaluateFtmoObjectives(input({ challenge: { ...challenge, phase: "funded" } }));
    expect(row(rows, "min_days").state).toBe("non_source");
    expect(row(rows, "profit_target").state).toBe("non_source");
  });
});
