/**
 * FTMO challenge objectives, evaluated against what this system can see
 * (T12).
 *
 * Mirrors the "Objectifs" table of FTMO MetriX — objective, result, state —
 * in the same order, with one addition MetriX does not have: each row says
 * how its number was obtained and what it cannot see. The cockpit reads
 * closed trades and the current balance/equity; FTMO reads its own server.
 * Where the two can differ, the row says so instead of presenting the
 * approximation as FTMO's verdict.
 *
 * Nothing here decides anything (ADR 0007). The loss limits are enforced by
 * the Risk Engine's gates; this only reports how far the challenge is.
 */

import { formatMoney, formatSignedMoney } from "@/lib/format";
import type { RiskPolicy } from "@/lib/domain/risk";
import type { JournalTrade } from "@/lib/journal/types";
import { ftmoObjectives, type FtmoChallenge } from "./ftmo";

/**
 * Two kinds of objective, two vocabularies: a target is reached or not yet;
 * a limit is respected or breached. "non_source" is a rule this phase has not
 * been given a sourced value for — shown, never guessed.
 */
export type ObjectiveState = "atteint" | "en_cours" | "respecte" | "depasse" | "non_source";

export interface ObjectiveRow {
  key: "min_days" | "daily_loss" | "max_loss" | "profit_target";
  label: string;
  result: string;
  state: ObjectiveState;
  /** How the result was obtained, and what it cannot see. */
  note: string;
}

export interface ObjectivesInput {
  challenge: FtmoChallenge;
  policy: RiskPolicy;
  /** Every closed trade of the account — one FTMO account is one challenge. */
  trades: JournalTrade[];
  balance: number;
  equity: number;
}

function utcDay(iso: string): string {
  return iso.slice(0, 10);
}

function minTradingDaysRow(input: ObjectivesInput, required: number | null): ObjectiveRow {
  if (required === null) {
    return {
      key: "min_days",
      label: "Jours de trading minimum",
      result: "—",
      state: "non_source",
      note: "Règle de cette phase non sourcée — TODO(FTMO-rules).",
    };
  }

  const days = new Set<string>();
  let countedAtClose = 0;
  for (const trade of input.trades) {
    if (trade.openedAt) {
      days.add(utcDay(trade.openedAt));
    } else {
      days.add(utcDay(trade.closedAt));
      countedAtClose += 1;
    }
  }

  const note =
    "Jours distincts avec au moins une position ouverte, en UTC — FTMO compte en CE(S)T, " +
    "un trade ouvert en fin de soirée peut tomber sur un autre jour chez eux." +
    (countedAtClose > 0
      ? ` ${countedAtClose} trade(s) sans ouverture enregistrée compté(s) à la clôture.`
      : "");

  return {
    key: "min_days",
    label: `${required} jours de trading minimum`,
    result: `${days.size} jour${days.size === 1 ? "" : "s"}`,
    state: days.size >= required ? "atteint" : "en_cours",
    note,
  };
}

function dailyLossRow(input: ObjectivesInput): ObjectiveRow {
  const limit = (input.challenge.accountSize * input.policy.dailyLossLimitPercent) / 100;

  const byDay = new Map<string, number>();
  for (const trade of input.trades) {
    const day = utcDay(trade.closedAt);
    byDay.set(day, (byDay.get(day) ?? 0) + trade.realizedPnl);
  }
  let worstDay: string | null = null;
  let worstPnl = 0;
  for (const [day, pnl] of byDay) {
    if (pnl < worstPnl) {
      worstPnl = pnl;
      worstDay = day;
    }
  }

  return {
    key: "daily_loss",
    label: `Perte journalière max ${formatSignedMoney(-limit)}`,
    result:
      worstDay === null
        ? "aucune journée perdante"
        : `pire journée ${formatSignedMoney(worstPnl)} (${worstDay})`,
    state: worstPnl <= -limit ? "depasse" : "respecte",
    note:
      "P&L réalisé par jour de clôture (UTC). FTMO juge l'equity, flottant compris, sur une " +
      "journée CE(S)T : une journée peut avoir franchi la limite en cours de séance sans que " +
      "le réalisé le montre. Le gate temps réel, lui, lit l'equity.",
  };
}

function maxLossRow(input: ObjectivesInput): ObjectiveRow {
  const limit = (input.challenge.accountSize * input.policy.maxDrawdownLimitPercent) / 100;
  const floor = input.challenge.accountSize - limit;
  const lowest = Math.min(input.balance, input.equity);

  return {
    key: "max_loss",
    label: `Perte max ${formatSignedMoney(-limit)}`,
    result: `plancher ${formatMoney(floor)} · marge ${formatMoney(Math.max(0, lowest - floor))}`,
    state: lowest <= floor ? "depasse" : "respecte",
    note:
      "État actuel, sur le plus bas du solde et de l'equity. Sans historique d'equity, un " +
      "franchissement passé puis effacé ne se voit pas ici — FTMO, lui, l'aurait vu.",
  };
}

function profitTargetRow(input: ObjectivesInput, percent: number | null): ObjectiveRow {
  if (percent === null) {
    return {
      key: "profit_target",
      label: "Objectif de profit",
      result: "—",
      state: "non_source",
      note: "Règle de cette phase non sourcée — TODO(FTMO-rules).",
    };
  }

  const target = (input.challenge.accountSize * percent) / 100;
  const progress = input.balance - input.challenge.accountSize;
  return {
    key: "profit_target",
    label: `Objectif de profit ${formatSignedMoney(target)}`,
    result: `${formatSignedMoney(progress)} sur ${formatSignedMoney(target)}`,
    state: progress >= target ? "atteint" : "en_cours",
    note: "Mesuré sur le solde : une position ouverte ne compte qu'une fois fermée.",
  };
}

/** In MetriX's order: trading days, daily loss, overall loss, profit target. */
export function evaluateFtmoObjectives(input: ObjectivesInput): ObjectiveRow[] {
  const { minTradingDays, profitTargetPercent } = ftmoObjectives(input.challenge);
  return [
    minTradingDaysRow(input, minTradingDays),
    dailyLossRow(input),
    maxLossRow(input),
    profitTargetRow(input, profitTargetPercent),
  ];
}
